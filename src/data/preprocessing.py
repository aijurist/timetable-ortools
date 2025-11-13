"""
Data Preprocessing Module

Extends raw data from data_loader.py with intermediate data structures using OR-Tools optimization:
- Group creation via CourseGroupOptimizer (optimized distribution of course instances)
- Group requirements calculation
- Instance-to-group mapping
- Lab requirements extraction
- Core lab mapping
- Visualization of group distribution as heatmaps

Transforms raw DataContainer into ExtendedDataContainer with enriched information
for variable creation and constraint application.
"""

import logging
import os
import json
from typing import Dict, List, Set, Tuple, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from course_group_optimizer import CourseGroupOptimizer

logger = logging.getLogger(__name__)


@dataclass
class ExtendedDataContainer:
    """Extended data container with intermediate processing results."""
    # Original data from data_loader
    courses: List[Dict[str, Any]]
    rooms: List[Dict[str, Any]]
    teachers: Set[str]
    departments: Set[str]
    time_slots: Dict[str, List]
    days: List[str]
    num_days: int
    day_order: Dict[str, List]
    room_registry: Dict[str, Any]
    horizon: int
    load_timestamp: str
    
    # Extended data from preprocessing
    groups: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """
    Format: {
        'dept_name|sem': {
            'name': 'dept_name|sem',
            'department': 'dept_name',
            'semester': sem,
            'student_count': int,
            'instances': [...],  # course instances optimally distributed to this group
            'group_index': int,  # position in optimized groups list
        },
        ...
    }
    """
    
    group_requirements: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    """
    Format: {
        'group_key': {
            'theory_slots_needed': int,
            'courses': [list of course codes],
            'teachers': [list of teacher IDs],
            'lab_courses': [list of lab course codes],
            'theory_courses': [list of theory course codes],
        },
        ...
    }
    """
    
    instance_group_mapping: Dict[str, str] = field(default_factory=dict)
    """
    Format: {
        'course_code|teacher': 'group_key',
        ...
    }
    """
    
    lab_requirements: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    """
    Format: {
        'teacher_id': [
            {
                'course_code': str,
                'session_count': int,
                'core_lab': bool,
                'capacity': int,
                'department': str,
                'semester': int,
            },
            ...
        ],
        ...
    }
    """
    
    core_lab_mapping: Dict[str, Set[str]] = field(default_factory=dict)
    """
    Format: {
        'core_group_key': {'core_lab_1', 'core_lab_2', ...},
        ...
    }
    """
    
    optimization_metadata: Dict[str, Any] = field(default_factory=dict)
    """
    Metadata about group optimization process:
    {
        'dept_sem': {
            'optimizer_status': bool,
            'num_groups': int,
            'total_instances': int,
            'optimization_time': float,
        },
        ...
    }
    """


class GroupVisualization:
    """Generate visualization matrices for group distribution."""
    
    def __init__(self, output_root: str = "output/course_groups"):
        """
        Initialize visualization generator.
        
        Args:
            output_root: Root directory for all visualizations (default: output/course_groups)
        """
        self.output_root = output_root
        self.logger = logging.getLogger(__name__)
        self._ensure_output_structure()
    
    def _ensure_output_structure(self) -> None:
        """Create indexed folder structure for current run."""
        os.makedirs(self.output_root, exist_ok=True)
        
        # Find next run index
        existing_runs = []
        if os.path.exists(self.output_root):
            existing_runs = [
                d for d in os.listdir(self.output_root)
                if d.startswith('run_') and os.path.isdir(os.path.join(self.output_root, d))
            ]
        
        next_index = len(existing_runs) + 1
        self.run_dir = os.path.join(self.output_root, f'run_{next_index:03d}')
        os.makedirs(self.run_dir, exist_ok=True)
        
        self.logger.info(f"📂 Visualization output: {self.run_dir}")
    
    def visualize_group_distribution(self, groups: Dict[str, Dict[str, Any]]) -> None:
        """
        Generate heatmap visualization for group distribution.
        
        Args:
            groups: Dictionary of groups with instances
        """
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
        except ImportError:
            self.logger.warning("⚠️ matplotlib/seaborn not available, skipping visualization")
            return
        
        self.logger.info("🎨 Generating group distribution visualizations...")
        
        # Group by department and semester
        dept_sem_groups = defaultdict(list)
        for group_key, group_info in groups.items():
            dept = group_info['department']
            sem = group_info['semester']
            dept_sem_groups[(dept, sem)].append((group_key, group_info))
        
        # Create visualization for each dept-semester
        for (dept, sem), groups_list in dept_sem_groups.items():
            self._create_dept_sem_heatmap(dept, sem, groups_list)
        
        # Create metadata file
        self._save_metadata(groups)
        
        self.logger.info(f"✅ Visualizations saved to: {self.run_dir}")
    
    def _create_dept_sem_heatmap(self, dept: str, sem: int, groups_list: List[Tuple[str, Dict]]) -> None:
        """
        Create heatmap for a department-semester combination.
        
        Args:
            dept: Department name
            sem: Semester number
            groups_list: List of (group_key, group_info) tuples
        """
        try:
            import matplotlib.pyplot as plt
            import seaborn as sns
            import numpy as np
        except ImportError:
            return
        
        self.logger.info(f"  📊 {dept} - Semester {sem}")
        
        # Build course-group matrix
        course_group_matrix = {}
        all_courses = set()
        group_names = []
        
        for group_idx, (group_key, group_info) in enumerate(groups_list):
            group_name = f"G{group_idx + 1}"
            group_names.append(group_name)
            
            course_teacher_counts = {}
            for instance in group_info['instances']:
                course_code = instance.get('code', '')
                teacher_id = instance.get('teacher', '')
                all_courses.add(course_code)
                
                if course_code not in course_teacher_counts:
                    course_teacher_counts[course_code] = set()
                course_teacher_counts[course_code].add(teacher_id)
            
            for course_code, teachers in course_teacher_counts.items():
                if course_code not in course_group_matrix:
                    course_group_matrix[course_code] = {}
                course_group_matrix[course_code][group_name] = len(teachers)
        
        if not all_courses or not group_names:
            self.logger.warning(f"  ⚠️ No data for {dept} Semester {sem}")
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
        fig, ax = plt.subplots(figsize=(max(10, len(group_names) * 1.5), max(8, len(courses_list) * 0.5)))
        matrix_array = np.array(matrix_data)
        
        # Create heatmap
        sns.heatmap(matrix_array,
                   xticklabels=group_names,
                   yticklabels=courses_list,
                   annot=True,
                   fmt='d',
                   cmap='YlOrRd',
                   cbar_kws={'label': 'Teacher Assignments'},
                   linewidths=0.5,
                   ax=ax)
        
        # Labels and title
        ax.set_title(
            f'Course-to-Group Distribution Matrix\n{dept} - Semester {sem}',
            fontsize=14,
            fontweight='bold',
            pad=20
        )
        ax.set_xlabel('Groups', fontsize=12, fontweight='bold')
        ax.set_ylabel('Courses', fontsize=12, fontweight='bold')
        
        # Add statistics
        total_assignments = np.sum(matrix_array)
        max_assignments = np.max(matrix_array) if matrix_array.size > 0 else 0
        courses_with_choice = sum(1 for course in courses_list
                                 if np.sum([course_group_matrix.get(course, {}).get(g, 0) 
                                          for g in group_names]) > 1)
        
        stats_text = (
            f'Statistics: {len(courses_list)} courses, {len(group_names)} groups\n'
            f'Total Assignments: {int(total_assignments)}, Max per Cell: {int(max_assignments)}\n'
            f'Courses with Multiple Groups: {courses_with_choice}/{len(courses_list)}'
        )
        
        fig.text(0.02, 0.02, stats_text, fontsize=9,
                bbox=dict(boxstyle="round,pad=0.5", facecolor="lightgray", alpha=0.8))
        
        plt.tight_layout()
        
        # Save figure
        safe_dept = dept.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
        filename = f'distribution_{safe_dept}_S{sem}.png'
        filepath = os.path.join(self.run_dir, filename)
        plt.savefig(filepath, dpi=300, bbox_inches='tight')
        plt.close()
        
        self.logger.info(f"    ✅ Saved: {filename}")
        
        # Save text summary
        self._save_dept_sem_summary(dept, sem, courses_list, group_names, 
                                   course_group_matrix, matrix_array)
    
    def _save_dept_sem_summary(self, dept: str, sem: int, courses_list: List[str],
                               group_names: List[str], matrix: Dict, array: Any) -> None:
        """Save text summary for dept-semester."""
        try:
            import numpy as np
        except ImportError:
            return
        
        safe_dept = dept.replace(" ", "_").replace("&", "and").replace("(", "").replace(")", "")
        filename = f'summary_{safe_dept}_S{sem}.txt'
        filepath = os.path.join(self.run_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"Course-Group Distribution Summary\n")
            f.write(f"Department: {dept}\n")
            f.write(f"Semester: {sem}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            
            total_assignments = int(np.sum(array))
            f.write(f"OVERVIEW:\n")
            f.write(f"  Courses: {len(courses_list)}\n")
            f.write(f"  Groups: {len(group_names)}\n")
            f.write(f"  Total Teacher Assignments: {total_assignments}\n\n")
            
            f.write(f"COURSE DISTRIBUTION:\n")
            for course in courses_list:
                course_data = matrix.get(course, {})
                groups_with_course = [g for g, count in course_data.items() if count > 0]
                total_teachers = sum(course_data.values())
                f.write(f"  {course}: {len(groups_with_course)} groups, {total_teachers} teachers\n")
                for group_name in groups_with_course:
                    f.write(f"    └─ {group_name}: {course_data[group_name]} teachers\n")
            
            f.write(f"\nGROUP COMPOSITION:\n")
            for idx, group_name in enumerate(group_names):
                col_data = array[:, idx]
                total_in_group = int(np.sum(col_data))
                courses_in_group = sum(1 for val in col_data if val > 0)
                f.write(f"  {group_name}: {courses_in_group} courses, {total_in_group} teachers\n")
    
    def _save_metadata(self, groups: Dict[str, Dict[str, Any]]) -> None:
        """Save metadata about the visualization run."""
        metadata = {
            'timestamp': datetime.now().isoformat(),
            'total_groups': len(groups),
            'group_keys': list(groups.keys()),
            'summary_by_dept_sem': {},
        }
        
        # Add summary stats
        for group_key, group_info in groups.items():
            dept = group_info['department']
            sem = group_info['semester']
            key = f"{dept}|{sem}"
            
            if key not in metadata['summary_by_dept_sem']:
                metadata['summary_by_dept_sem'][key] = {
                    'department': dept,
                    'semester': sem,
                    'groups': 0,
                    'total_instances': 0,
                    'total_students': 0,
                }
            
            metadata['summary_by_dept_sem'][key]['groups'] += 1
            metadata['summary_by_dept_sem'][key]['total_instances'] += len(group_info['instances'])
            metadata['summary_by_dept_sem'][key]['total_students'] += group_info['student_count']
        
        metadata_path = os.path.join(self.run_dir, 'metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)
        
        self.logger.info(f"    ✅ Saved metadata.json")


class DataPreprocessor:
    """Preprocess raw data using OR-Tools optimization for group creation."""
    
    def __init__(self, data: Dict[str, Any], optimize_groups: bool = True, visualize: bool = True):
        """
        Initialize preprocessor with raw data.
        
        Args:
            data: Raw data dictionary from data_loader.load()
            optimize_groups: Whether to use OR-Tools for group optimization (default True)
            visualize: Whether to generate visualization heatmaps (default True)
        """
        self.data = data
        self.optimize_groups_flag = optimize_groups
        self.visualize_flag = visualize
        self.logger = logging.getLogger(__name__)
        self.optimization_metadata = {}
        self.visualizer = GroupVisualization() if visualize else None
        
    def process(self) -> ExtendedDataContainer:
        """
        Process raw data into extended container.
        
        Returns:
            ExtendedDataContainer with all intermediate structures
        """
        self.logger.info("=" * 80)
        self.logger.info("STARTING DATA PREPROCESSING")
        self.logger.info("=" * 80)
        
        # # Create groups - using optimization if enabled
        # if self.optimize_groups_flag:
        groups = self._create_optimized_groups()
        # else:
        #     groups = self._create_simple_groups()
        self.logger.info(f"Created {len(groups)} groups")
        
        if self.visualize_flag and self.visualizer:
            self.visualizer.visualize_group_distribution(groups)
        
        group_requirements = self._create_group_requirements(groups)
        self.logger.info(f"Calculated requirements for {len(group_requirements)} groups")
        
        instance_group_mapping = self._create_instance_group_mapping(groups)
        self.logger.info(f"Mapped {len(instance_group_mapping)} course instances to groups")
        
        lab_requirements = self._extract_lab_requirements()
        self.logger.info(f"Extracted lab requirements for {len(lab_requirements)} teachers")
        
        core_lab_mapping = self._create_core_lab_mapping(groups)
        self.logger.info(f"Mapped {len(core_lab_mapping)} core groups to core labs")
        
        extended = ExtendedDataContainer(
            courses=self.data['courses'],
            rooms=self.data['rooms'],
            teachers=self.data['teachers'],
            departments=self.data['departments'],
            time_slots=self.data['time_slots'],
            days=self.data['days'],
            num_days=self.data['num_days'],
            day_order=self.data['day_order'],
            room_registry=self.data['room_registry'],
            horizon=self.data['horizon'],
            load_timestamp=self.data['load_timestamp'],
            groups=groups,
            group_requirements=group_requirements,
            instance_group_mapping=instance_group_mapping,
            lab_requirements=lab_requirements,
            core_lab_mapping=core_lab_mapping,
            optimization_metadata=self.optimization_metadata,
        )
        
        self.logger.info("=" * 80)
        self.logger.info("DATA PREPROCESSING COMPLETE")
        self.logger.info("=" * 80)
        
        return extended
    
    def _create_optimized_groups(self) -> Dict[str, Dict[str, Any]]:
        """
        Create groups using OR-Tools optimization.
        
        Groups courses by dept+semester, then optimizes distribution within each group.
        
        Returns:
            Dictionary of group structures
        """
        groups = {}
        
        # First, collect courses by dept+semester
        dept_sem_courses = defaultdict(list)
        for course in self.data['courses']:
            dept = course.get('department', 'Unknown')
            sem = course.get('semester', 0)
            key = f"{dept}|{sem}"
            dept_sem_courses[key].append(course)
        
        # For each dept-semester combination, optimize group distribution
        group_counter = 0
        for dept_sem_key, courses_in_group in dept_sem_courses.items():
            dept, sem = dept_sem_key.split('|')
            

            optimizer = CourseGroupOptimizer(dept, int(sem), self.logger)
            success = optimizer.optimize_distribution(courses_in_group)
            
            self.optimization_metadata[dept_sem_key] = {
                'optimizer_status': success,
                'num_groups': len(optimizer.get_groups()) if success else 0,
                'total_instances': len(courses_in_group),
            }
            
            if success:
                for group_idx, group_instances in enumerate(optimizer.get_groups()):
                    student_count = max(
                        (c.get('student_count', 0) for c in group_instances),
                        default=0
                    )
                    
                    group_key = f"{dept_sem_key}_g{group_idx}"
                    groups[group_key] = {
                        'name': group_key,
                        'department': dept,
                        'semester': int(sem),
                        'student_count': student_count,
                        'instances': group_instances,
                        'group_index': group_idx,
                        'optimization_applied': True,
                    }
                    group_counter += 1
                    
                self.logger.info(
                    f"Optimized {dept_sem_key}: {len(courses_in_group)} instances → "
                    f"{len(optimizer.get_groups())} balanced groups"
                )
            else:
                self.logger.warning(f"Optimization failed for {dept_sem_key}, using simple grouping")
                student_count = max(
                    (c.get('student_count', 0) for c in courses_in_group),
                    default=0
                )
                group_key = dept_sem_key
                groups[group_key] = {
                    'name': group_key,
                    'department': dept,
                    'semester': int(sem),
                    'student_count': student_count,
                    'instances': courses_in_group,
                    'group_index': 0,
                    'optimization_applied': False,
                }
                group_counter += 1
        
        self.logger.info(f"Created {group_counter} total groups using optimization")

        print(groups)
        return groups
    
    def _create_simple_groups(self) -> Dict[str, Dict[str, Any]]:
        """
        Create groups by department and semester (simple approach, no optimization).
        
        Returns:
            Dictionary of group structures
        """
        groups = {}
        dept_sem_courses = defaultdict(list)
        
        for course in self.data['courses']:
            dept = course.get('department', 'Unknown')
            sem = course.get('semester', 0)
            key = f"{dept}|{sem}"
            dept_sem_courses[key].append(course)
        
        for key, courses_list in dept_sem_courses.items():
            dept, sem = key.split('|')
            groups[key] = {
                'name': key,
                'department': dept,
                'semester': int(sem),
                'student_count': max((c.get('student_count', 0) for c in courses_list), default=0),
                'instances': courses_list,
                'group_index': 0,
                'optimization_applied': False,
            }
        
        self.logger.debug(f"Created {len(groups)} groups (simple grouping)")
        return groups
    
    def _create_group_requirements(self, groups: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Calculate requirements for each group.
        
        Requirements include:
        - Total theory slots needed
        - List of courses
        - List of teachers
        - Lab/Theory course separation
        
        Args:
            groups: Groups dictionary
        
        Returns:
            Dictionary mapping group_key -> requirements
        """
        group_reqs = {}
        
        for group_key, group_info in groups.items():
            theory_slots = 0
            courses = []
            teachers = set()
            lab_courses = []
            theory_courses = []
            
            for course in group_info['instances']:
                # Count theory sessions
                theory_sessions = course.get('sessions_theory', 0)
                theory_slots += theory_sessions
                
                course_code = course.get('code', '')
                courses.append(course_code)
                teacher = course.get('teacher', '')
                if teacher:
                    teachers.add(teacher)
                
                # Categorize by type
                if course.get('sessions_lab', 0) > 0:
                    lab_courses.append(course_code)
                if theory_sessions > 0:
                    theory_courses.append(course_code)
            
            group_reqs[group_key] = {
                'theory_slots_needed': theory_slots,
                'courses': courses,
                'teachers': list(teachers),
                'lab_courses': lab_courses,
                'theory_courses': theory_courses,
            }
            
            self.logger.debug(
                f"Group {group_key}: {theory_slots} theory slots, "
                f"{len(courses)} courses ({len(lab_courses)} lab, {len(theory_courses)} theory), "
                f"{len(teachers)} teachers"
            )
        
        return group_reqs
    
    def _create_instance_group_mapping(self, groups: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
        """
        Map each course instance to its group.
        
        Instance key: 'course_code|teacher_id'
        Group key: 'dept|semester' or 'dept|semester_gX' (from optimization)
        
        Args:
            groups: Groups dictionary
        
        Returns:
            Dictionary mapping instance_key -> group_key
        """
        mapping = {}
        
        for group_key, group_info in groups.items():
            for course in group_info['instances']:
                course_code = course.get('code', '')
                teacher_id = course.get('teacher', '')
                
                instance_key = f"{course_code}|{teacher_id}"
                mapping[instance_key] = group_key
        
        self.logger.debug(f"Created mapping for {len(mapping)} course instances")
        return mapping
    
    def _extract_lab_requirements(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract lab requirements per teacher.
        
        Lab requirements come from courses with lab_sessions > 0.
        
        Returns:
            Dictionary mapping teacher_id -> list of lab requirements
        """
        lab_reqs = defaultdict(list)
        
        for course in self.data['courses']:
            lab_sessions = course.get('sessions_lab', 0)
            
            # Only process courses with lab sessions
            if lab_sessions > 0:
                teacher_id = course.get('teacher', '')
                
                if teacher_id:
                    lab_reqs[teacher_id].append({
                        'course_code': course.get('code', ''),
                        'session_count': lab_sessions,
                        'core_lab': course.get('core_lab', False),
                        'capacity': course.get('student_count', 0),
                        'department': course.get('department', ''),
                        'semester': course.get('semester', 0),
                    })
        
        self.logger.debug(
            f"Extracted lab requirements for {len(lab_reqs)} teachers, "
            f"{sum(len(v) for v in lab_reqs.values())} total lab courses"
        )
        
        return dict(lab_reqs)
    
    def _create_core_lab_mapping(self, groups: Dict[str, Dict[str, Any]]) -> Dict[str, Set[str]]:
        """
        Map core groups to core lab courses.
        
        Core groups: dept|semester where courses have core_lab=True
        Core labs: course codes that are core labs
        
        Args:
            groups: Groups dictionary
        
        Returns:
            Dictionary mapping core_group_key -> set of compatible core lab codes
        """
        core_mapping = {}
        
        # Find all core lab courses
        core_labs_by_dept_sem = defaultdict(set)
        
        for course in self.data['courses']:
            if course.get('core_lab', False):
                dept = course.get('department', 'Unknown')
                sem = course.get('semester', 0)
                code = course.get('code', '')
                
                key = f"{dept}|{sem}"
                core_labs_by_dept_sem[key].add(code)
        
        # Map groups to core labs
        for group_key, core_labs in core_labs_by_dept_sem.items():
            if group_key in groups:
                core_mapping[group_key] = core_labs
                self.logger.debug(
                    f"Core group {group_key} -> {len(core_labs)} core labs: {core_labs}"
                )
        
        return core_mapping


def preprocess_data(data: Dict[str, Any], optimize_groups: bool = True, visualize: bool = True) -> ExtendedDataContainer:
    """
    Convenience function to preprocess data in one call.
    
    Args:
        data: Raw data dictionary from data_loader.load()
        optimize_groups: Whether to use OR-Tools optimization for groups (default True)
        visualize: Whether to generate visualization heatmaps (default True)
    
    Returns:
        ExtendedDataContainer with all intermediate structures
    """
    preprocessor = DataPreprocessor(data, optimize_groups, visualize)
    return preprocessor.process()


def print_preprocessing_summary(extended: ExtendedDataContainer) -> None:
    """
    Print summary of preprocessing results.
    
    Args:
        extended: ExtendedDataContainer from preprocessing
    """
    print("\n" + "=" * 80)
    print("PREPROCESSING SUMMARY")
    print("=" * 80)
    
    print(f"\nGroups Created: {len(extended.groups)}")
    for group_key, group_info in extended.groups.items():
        count = group_info['student_count']
        courses = len(group_info['instances'])
        opt_status = "✓ Optimized" if group_info.get('optimization_applied', False) else "Simple"
        print(f"  {group_key}: {courses} courses, {count} students [{opt_status}]")
    
    print(f"\nGroup Requirements: {len(extended.group_requirements)}")
    total_theory_slots = 0
    total_lab_courses = 0
    for group_key, reqs in extended.group_requirements.items():
        slots = reqs['theory_slots_needed']
        total_theory_slots += slots
        total_lab_courses += len(reqs['lab_courses'])
        print(f"  {group_key}: {slots} theory slots, "
              f"{len(reqs['courses'])} courses, {len(reqs['teachers'])} teachers")
    print(f"  Total theory slots needed: {total_theory_slots}")
    print(f"  Total lab courses: {total_lab_courses}")
    
    print(f"\nInstance-to-Group Mapping: {len(extended.instance_group_mapping)} instances")
    
    print(f"\nLab Requirements: {len(extended.lab_requirements)} teachers")
    total_lab_assignments = sum(len(v) for v in extended.lab_requirements.values())
    print(f"  Total lab assignments: {total_lab_assignments}")
    for teacher_id, reqs in list(extended.lab_requirements.items())[:5]:
        print(f"  {teacher_id}: {len(reqs)} lab courses")
    if len(extended.lab_requirements) > 5:
        print(f"  ... and {len(extended.lab_requirements) - 5} more teachers")
    
    print(f"\nCore Lab Mapping: {len(extended.core_lab_mapping)} core groups")
    for group_key, core_labs in extended.core_lab_mapping.items():
        print(f"  {group_key} -> {core_labs}")
    
    if extended.optimization_metadata:
        print(f"\nOptimization Metadata:")
        for dept_sem, meta in extended.optimization_metadata.items():
            status = "✓ Success" if meta['optimizer_status'] else "✗ Fallback"
            print(f"  {dept_sem}: {meta['num_groups']} groups from {meta['total_instances']} instances [{status}]")
    
    print("=" * 80 + "\n")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    
    # Load raw data
    from data_loader import load_data
    
    try:
        raw_data = load_data(
            courses_csv='../../data/Computer-Depts-LTPC.csv',
            rooms_csv='../../data/block_wise/techlongue.csv',
        )
        
        extended = preprocess_data(raw_data, optimize_groups=True, visualize=True)
        
        # print_preprocessing_summary(extended)
        
        print("\n" + "=" * 80)
        print("📂 Visualizations saved to: output/course_groups/")
        print("=" * 80)
        
    except Exception as e:
        logger.error(f"Failed to preprocess data: {e}")
        import traceback
        traceback.print_exc()
