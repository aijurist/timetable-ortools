import pandas as pd
import os
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns
import numpy as np
from datetime import datetime

def verify_lab_shift_compliance():
    """Verify lab allocation compliance with teacher shift constraints and analyze distribution."""
    
    print("🔍 LAB SHIFT COMPLIANCE VERIFICATION")
    print("=" * 80)
    
    # Load shift definitions
    shift_definitions = {
        'shift1': {
            'time_range': '8:00 - 3:00',
            'allowed_lab_sessions': ['L1', 'L2', 'L3'],
            'description': 'Morning to Early Afternoon Shift'
        },
        'shift2': {
            'time_range': '10:00 - 5:00', 
            'allowed_lab_sessions': ['L2', 'L3', 'L4'],
            'description': 'Mid-day to Afternoon Shift'
        },
        'shift3': {
            'time_range': '12:00 - 7:00',
            'allowed_lab_sessions': ['L4', 'L5', 'L6'],
            'description': 'Afternoon to Evening Shift'
        }
    }
    
    # Lab session to time mapping
    lab_sessions = {
        'L1': ['8:00 - 8:50', '8:50 - 9:40'],      # 8:00 - 9:40
        'L2': ['9:50 - 10:40', '10:40 - 11:30'],   # 9:50 - 11:30  
        'L3': ['11:50 - 12:40', '12:40 - 1:30'],   # 11:50 - 1:30
        'L4': ['1:50 - 2:40', '2:40 - 3:30'],      # 1:50 - 3:30
        'L5': ['3:50 - 4:40', '4:40 - 5:30'],      # 3:50 - 5:30
        'L6': ['5:30 - 6:20', '6:20 - 7:10']       # 5:30 - 7:10
    }
    
    # Find latest lab schedule
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("❌ No output directory found!")
        return False
    
    # Find lab schedule
    lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    if not lab_folders:
        print("❌ No lab schedule found! Run lab_scheduler.py first.")
        return False
    
    latest_lab_folder = max(lab_folders)
    print(f"📁 Using lab schedule: {latest_lab_folder}")
    
    # Load lab schedule
    combined_schedule_file = os.path.join(output_dir, latest_lab_folder, "combined_theory_lab_schedule.csv")
    if not os.path.exists(combined_schedule_file):
        print(f"❌ Combined schedule file not found: {combined_schedule_file}")
        return False
    
    schedule_df = pd.read_csv(combined_schedule_file)
    lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    
    if len(lab_data) == 0:
        print("❌ No lab assignments found in schedule!")
        return False
    
    print(f"📊 Found {len(lab_data)} lab assignments to verify")
    
    # Find latest theory schedule for shift data
    theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if not theory_folders:
        print("❌ No theory schedule found!")
        return False
    
    latest_theory_folder = max(theory_folders)
    shift_file_path = os.path.join(output_dir, latest_theory_folder, 'teacher_daily_shifts.csv')
    
    if not os.path.exists(shift_file_path):
        print(f"❌ Teacher shift file not found: {shift_file_path}")
        return False
    
    print(f"📁 Using shift data: {latest_theory_folder}/teacher_daily_shifts.csv")
    shift_df = pd.read_csv(shift_file_path)
    
    # Create teacher shift lookup
    teacher_shifts = {}
    for _, row in shift_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        shift = row['shift']
        effective_shift = shift if shift != 'no_classes' else row.get('recommended_shift', '')
        
        if teacher_id not in teacher_shifts:
            teacher_shifts[teacher_id] = {}
        teacher_shifts[teacher_id][day] = effective_shift
    
    print(f"📊 Loaded shift data for {len(teacher_shifts)} teachers")
    
    # Map time intervals to lab sessions
    def map_time_to_lab_session(time_interval):
        time_to_session_map = {
            '8:00 - 8:50': 'L1', '8:50 - 9:40': 'L1',
            '9:50 - 10:40': 'L2', '10:40 - 11:30': 'L2',
            '11:50 - 12:40': 'L3', '12:40 - 1:30': 'L3',
            '1:50 - 2:40': 'L4', '2:40 - 3:30': 'L4',
            '3:50 - 4:40': 'L5', '4:40 - 5:30': 'L5',
            '5:30 - 6:20': 'L6', '6:20 - 7:10': 'L6'
        }
        return time_to_session_map.get(time_interval, 'Unknown')
    
    # Analyze shift compliance
    print("\n🔍 SHIFT COMPLIANCE ANALYSIS:")
    print("-" * 60)
    
    violations = []
    compliance_stats = {
        'total_assignments': len(lab_data),
        'compliant_assignments': 0,
        'violations': 0,
        'by_shift': defaultdict(lambda: {'total': 0, 'compliant': 0, 'violations': 0})
    }
    
    allocation_distribution = defaultdict(lambda: defaultdict(int))
    teacher_distribution = defaultdict(lambda: defaultdict(int))
    
    for _, row in lab_data.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        time_interval = row['time_interval']
        course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
        
        # Map time to lab session
        lab_session = map_time_to_lab_session(time_interval)
        
        # Get teacher's shift for this day
        teacher_shift = teacher_shifts.get(teacher_id, {}).get(day, 'unknown')
        
        # Update distribution tracking
        allocation_distribution[teacher_shift][lab_session] += 1
        teacher_distribution[teacher_id][lab_session] += 1
        
        # Update shift stats
        compliance_stats['by_shift'][teacher_shift]['total'] += 1
        
        # Check compliance
        is_compliant = False
        if teacher_shift in shift_definitions:
            allowed_sessions = shift_definitions[teacher_shift]['allowed_lab_sessions']
            is_compliant = lab_session in allowed_sessions
        elif teacher_shift == 'no_classes' or teacher_shift == 'unknown':
            # Allow all sessions if no shift constraint
            is_compliant = True
        
        if is_compliant:
            compliance_stats['compliant_assignments'] += 1
            compliance_stats['by_shift'][teacher_shift]['compliant'] += 1
        else:
            compliance_stats['violations'] += 1
            compliance_stats['by_shift'][teacher_shift]['violations'] += 1
            violations.append({
                'teacher': teacher_id,
                'day': day,
                'course': course_code,
                'assigned_session': lab_session,
                'time': time_interval,
                'teacher_shift': teacher_shift,
                'allowed_sessions': shift_definitions.get(teacher_shift, {}).get('allowed_lab_sessions', [])
            })
    
    # Calculate compliance rate
    compliance_rate = (compliance_stats['compliant_assignments'] / compliance_stats['total_assignments']) * 100
    
    print(f"Overall Compliance: {compliance_stats['compliant_assignments']}/{compliance_stats['total_assignments']} ({compliance_rate:.1f}%)")
    print(f"Total Violations: {compliance_stats['violations']}")
    
    print("\nCompliance by Shift Type:")
    for shift, stats in compliance_stats['by_shift'].items():
        if stats['total'] > 0:
            shift_rate = (stats['compliant'] / stats['total']) * 100
            shift_info = shift_definitions.get(shift, {})
            time_range = shift_info.get('time_range', 'Unknown')
            allowed = shift_info.get('allowed_lab_sessions', ['All'])
            
            print(f"  {shift} ({time_range}): {stats['compliant']}/{stats['total']} ({shift_rate:.1f}%)")
            print(f"    Allowed sessions: {', '.join(allowed)}")
            if stats['violations'] > 0:
                print(f"    ❌ Violations: {stats['violations']}")
    
    # Show violations in detail
    if violations:
        print(f"\n❌ SHIFT VIOLATIONS DETECTED ({len(violations)}):")
        print("-" * 80)
        for i, violation in enumerate(violations[:10]):  # Show first 10
            print(f"{i+1:2d}. Teacher {violation['teacher']} on {violation['day']}")
            print(f"     Course: {violation['course']}")
            print(f"     Assigned: {violation['assigned_session']} ({violation['time']})")
            print(f"     Shift: {violation['teacher_shift']}")
            print(f"     Allowed: {', '.join(violation['allowed_sessions'])}")
            print()
        
        if len(violations) > 10:
            print(f"     ... and {len(violations) - 10} more violations")
    else:
        print("\n✅ NO SHIFT VIOLATIONS FOUND!")
    
    # Lab session distribution analysis
    print(f"\n📊 LAB SESSION DISTRIBUTION BY SHIFT:")
    print("-" * 60)
    
    for shift, distribution in allocation_distribution.items():
        if sum(distribution.values()) > 0:
            shift_info = shift_definitions.get(shift, {})
            time_range = shift_info.get('time_range', 'Unknown')
            allowed = shift_info.get('allowed_lab_sessions', ['All'])
            
            print(f"\n{shift.upper()} ({time_range}):")
            print(f"  Allowed sessions: {', '.join(allowed)}")
            print(f"  Actual allocations:")
            
            total_allocations = sum(distribution.values())
            for session in ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']:
                count = distribution[session]
                percentage = (count / total_allocations) * 100 if total_allocations > 0 else 0
                
                # Mark violations
                is_allowed = session in allowed if allowed != ['All'] else True
                violation_mark = "" if is_allowed else " ❌"
                
                if count > 0:
                    session_times = " - ".join(lab_sessions[session])
                    print(f"    {session} ({session_times}): {count:3d} ({percentage:5.1f}%){violation_mark}")
    
    # Teacher-wise distribution summary
    print(f"\n👨‍🏫 TEACHER-WISE LAB SESSION DISTRIBUTION:")
    print("-" * 60)
    
    teacher_violation_summary = defaultdict(int)
    for teacher_id in sorted(teacher_distribution.keys()):
        teacher_allocations = teacher_distribution[teacher_id]
        total_teacher_labs = sum(teacher_allocations.values())
        
        # Get teacher's shifts across all days
        teacher_shift_pattern = []
        for day in ['tuesday', 'wed', 'thur', 'fri', 'sat']:
            shift = teacher_shifts.get(teacher_id, {}).get(day, 'unknown')
            teacher_shift_pattern.append(shift)
        
        # Count violations for this teacher
        teacher_violations = 0
        for violation in violations:
            if violation['teacher'] == teacher_id:
                teacher_violations += 1
        
        teacher_violation_summary[teacher_id] = teacher_violations
        
        if total_teacher_labs > 0:
            print(f"\nTeacher {teacher_id}: {total_teacher_labs} lab sessions")
            print(f"  Weekly shifts: {' → '.join(teacher_shift_pattern)}")
            
            for session, count in teacher_allocations.items():
                if count > 0:
                    percentage = (count / total_teacher_labs) * 100
                    session_times = " - ".join(lab_sessions[session])
                    print(f"    {session} ({session_times}): {count} ({percentage:.1f}%)")
            
            if teacher_violations > 0:
                print(f"    ❌ Violations: {teacher_violations}")
    
    # Generate visualization
    create_shift_compliance_visualization(
        allocation_distribution, 
        compliance_stats, 
        shift_definitions, 
        lab_sessions,
        os.path.join(output_dir, latest_lab_folder)
    )
    
    # Save detailed report
    save_shift_compliance_report(
        violations,
        compliance_stats,
        allocation_distribution,
        teacher_distribution,
        teacher_shifts,
        shift_definitions,
        lab_sessions,
        os.path.join(output_dir, latest_lab_folder)
    )
    
    print(f"\n📝 Detailed report saved to: {latest_lab_folder}/shift_compliance_report.txt")
    print(f"📈 Visualization saved to: {latest_lab_folder}/shift_compliance_analysis.png")
    
    # Return success if no violations
    return len(violations) == 0


def create_shift_compliance_visualization(allocation_distribution, compliance_stats, shift_definitions, lab_sessions, output_dir):
    """Create comprehensive shift compliance visualization."""
    
    plt.style.use('default')
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(20, 15))
    
    # 1. Overall compliance pie chart
    compliance_data = [
        compliance_stats['compliant_assignments'],
        compliance_stats['violations']
    ]
    labels = ['Compliant', 'Violations']
    colors = ['#2ecc71', '#e74c3c']
    
    ax1.pie(compliance_data, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax1.set_title('Overall Shift Compliance', fontsize=14, fontweight='bold')
    
    # 2. Compliance by shift type
    shifts = []
    compliant_counts = []
    violation_counts = []
    
    for shift, stats in compliance_stats['by_shift'].items():
        if stats['total'] > 0:
            shifts.append(shift)
            compliant_counts.append(stats['compliant'])
            violation_counts.append(stats['violations'])
    
    x = np.arange(len(shifts))
    width = 0.35
    
    bars1 = ax2.bar(x - width/2, compliant_counts, width, label='Compliant', color='#2ecc71', alpha=0.8)
    bars2 = ax2.bar(x + width/2, violation_counts, width, label='Violations', color='#e74c3c', alpha=0.8)
    
    ax2.set_xlabel('Shift Type')
    ax2.set_ylabel('Number of Assignments')
    ax2.set_title('Compliance by Shift Type', fontsize=14, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(shifts)
    ax2.legend()
    
    # Add value labels on bars
    for bar in bars1:
        height = bar.get_height()
        if height > 0:
            ax2.annotate(f'{int(height)}', xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    for bar in bars2:
        height = bar.get_height()
        if height > 0:
            ax2.annotate(f'{int(height)}', xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    
    # 3. Lab session distribution heatmap
    sessions = ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']
    shift_names = list(shift_definitions.keys())
    
    # Create matrix for heatmap
    matrix = []
    for shift in shift_names:
        row = []
        for session in sessions:
            count = allocation_distribution[shift][session]
            row.append(count)
        matrix.append(row)
    
    # Add unknown/no_classes if they exist
    for shift in allocation_distribution.keys():
        if shift not in shift_names and shift != 'unknown':
            shift_names.append(shift)
            row = [allocation_distribution[shift][session] for session in sessions]
            matrix.append(row)
    
    if matrix:
        im = ax3.imshow(matrix, cmap='YlOrRd', aspect='auto')
        ax3.set_xticks(range(len(sessions)))
        ax3.set_xticklabels(sessions)
        ax3.set_yticks(range(len(shift_names)))
        ax3.set_yticklabels(shift_names)
        ax3.set_title('Lab Session Allocation Heatmap', fontsize=14, fontweight='bold')
        
        # Add text annotations
        for i in range(len(shift_names)):
            for j in range(len(sessions)):
                if i < len(matrix) and j < len(matrix[i]):
                    value = matrix[i][j]
                    if value > 0:
                        ax3.text(j, i, str(value), ha="center", va="center", color="black", fontweight='bold')
        
        # Add colorbar
        cbar = plt.colorbar(im, ax=ax3)
        cbar.set_label('Number of Allocations')
    
    # 4. Allowed vs actual session usage
    shift_colors = ['#3498db', '#9b59b6', '#f39c12']
    
    for idx, (shift, shift_info) in enumerate(shift_definitions.items()):
        allowed_sessions = shift_info['allowed_lab_sessions']
        actual_counts = [allocation_distribution[shift][session] for session in sessions]
        
        # Mark allowed sessions
        colors = ['#2ecc71' if session in allowed_sessions else '#e74c3c' for session in sessions]
        
        # Plot as grouped bar chart
        x_pos = np.arange(len(sessions)) + idx * 0.25
        bars = ax4.bar(x_pos, actual_counts, 0.2, label=f'{shift}', alpha=0.8)
        
        # Color bars based on compliance
        for bar, session, color in zip(bars, sessions, colors):
            if allocation_distribution[shift][session] > 0:
                bar.set_color(color)
    
    ax4.set_xlabel('Lab Sessions')
    ax4.set_ylabel('Number of Allocations')
    ax4.set_title('Session Usage by Shift (Green=Allowed, Red=Violation)', fontsize=14, fontweight='bold')
    ax4.set_xticks(np.arange(len(sessions)) + 0.25)
    ax4.set_xticklabels(sessions)
    ax4.legend()
    
    plt.tight_layout()
    
    # Save the plot
    output_path = os.path.join(output_dir, 'shift_compliance_analysis.png')
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()


def save_shift_compliance_report(violations, compliance_stats, allocation_distribution, teacher_distribution, teacher_shifts, shift_definitions, lab_sessions, output_dir):
    """Save detailed shift compliance report."""
    
    report_path = os.path.join(output_dir, 'shift_compliance_report.txt')
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("LAB SHIFT COMPLIANCE VERIFICATION REPORT\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Updated shift definitions
        f.write("UPDATED SHIFT DEFINITIONS:\n")
        f.write("-" * 40 + "\n")
        for shift, info in shift_definitions.items():
            f.write(f"{shift}: {info['time_range']}\n")
            f.write(f"  Description: {info['description']}\n")
            f.write(f"  Allowed Lab Sessions: {', '.join(info['allowed_lab_sessions'])}\n")
            
            # Show session times
            f.write(f"  Session Times:\n")
            for session in info['allowed_lab_sessions']:
                session_times = " - ".join(lab_sessions[session])
                f.write(f"    {session}: {session_times}\n")
            f.write("\n")
        
        # Overall compliance
        f.write("OVERALL COMPLIANCE SUMMARY:\n")
        f.write("-" * 40 + "\n")
        compliance_rate = (compliance_stats['compliant_assignments'] / compliance_stats['total_assignments']) * 100
        f.write(f"Total Lab Assignments: {compliance_stats['total_assignments']}\n")
        f.write(f"Compliant Assignments: {compliance_stats['compliant_assignments']}\n")
        f.write(f"Violations: {compliance_stats['violations']}\n")
        f.write(f"Compliance Rate: {compliance_rate:.1f}%\n\n")
        
        # Compliance by shift
        f.write("COMPLIANCE BY SHIFT TYPE:\n")
        f.write("-" * 40 + "\n")
        for shift, stats in compliance_stats['by_shift'].items():
            if stats['total'] > 0:
                shift_rate = (stats['compliant'] / stats['total']) * 100
                f.write(f"{shift}: {stats['compliant']}/{stats['total']} ({shift_rate:.1f}%)\n")
                if stats['violations'] > 0:
                    f.write(f"  Violations: {stats['violations']}\n")
        f.write("\n")
        
        # Detailed violations
        if violations:
            f.write("DETAILED VIOLATION LIST:\n")
            f.write("-" * 40 + "\n")
            for i, violation in enumerate(violations, 1):
                f.write(f"{i:3d}. Teacher {violation['teacher']} on {violation['day']}\n")
                f.write(f"     Course: {violation['course']}\n")
                f.write(f"     Assigned Session: {violation['assigned_session']} ({violation['time']})\n")
                f.write(f"     Teacher Shift: {violation['teacher_shift']}\n")
                f.write(f"     Allowed Sessions: {', '.join(violation['allowed_sessions'])}\n\n")
        else:
            f.write("NO VIOLATIONS FOUND!\n\n")
        
        # Distribution analysis
        f.write("LAB SESSION DISTRIBUTION BY SHIFT:\n")
        f.write("-" * 40 + "\n")
        for shift, distribution in allocation_distribution.items():
            if sum(distribution.values()) > 0:
                total = sum(distribution.values())
                f.write(f"\n{shift.upper()} ({total} total allocations):\n")
                for session in ['L1', 'L2', 'L3', 'L4', 'L5', 'L6']:
                    count = distribution[session]
                    if count > 0:
                        percentage = (count / total) * 100
                        session_times = " - ".join(lab_sessions[session])
                        f.write(f"  {session} ({session_times}): {count:3d} ({percentage:5.1f}%)\n")
        
        # Teacher summary
        f.write("\n\nTEACHER-WISE VIOLATION SUMMARY:\n")
        f.write("-" * 40 + "\n")
        teacher_violations = defaultdict(int)
        for violation in violations:
            teacher_violations[violation['teacher']] += 1
        
        if teacher_violations:
            for teacher, count in sorted(teacher_violations.items()):
                f.write(f"Teacher {teacher}: {count} violations\n")
        else:
            f.write("No teachers have violations!\n")


if __name__ == "__main__":
    success = verify_lab_shift_compliance()
    if success:
        print("\n✅ All shift constraints are properly enforced!")
    else:
        print("\n❌ Shift constraint violations detected!")
        print("💡 Consider reviewing shift assignments or lab scheduling logic.") 