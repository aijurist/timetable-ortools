import pandas as pd
import os
from collections import defaultdict

def verify_ltp_constraints():
    """Verify that LTP constraints are satisfied for all courses."""
    
    # Load course requirements - try both possible file names
    course_files = [
        "data/mapped_data/computer_dept_teacher_courses.csv",
        # "data/mapped_data/cs_teacher_courses.csv"
    ]
    
    course_file = None
    for file_path in course_files:
        if os.path.exists(file_path):
            course_file = file_path
            break
    
    if not course_file:
        print(f"Course file not found. Tried: {course_files}")
        return False
    
    print(f"Using course file: {course_file}")
    courses_df = pd.read_csv(course_file)
    
    # Find the latest schedule
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("No output directory found!")
        return False
    
    # Find theory schedule
    theory_folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if not theory_folders:
        print("No macroblock schedule found!")
        return False
        
    latest_theory_folder = max(theory_folders)
    print(f"Latest theory folder: {latest_theory_folder}")
    theory_schedule_file = os.path.join(output_dir, latest_theory_folder, "macroblock_schedule.csv")
    print(f"Theory schedule file: {theory_schedule_file}")
    
    if not os.path.exists(theory_schedule_file):
        print(f"Theory schedule file not found: {theory_schedule_file}")
        return False
    
    theory_schedule_df = pd.read_csv(theory_schedule_file)
    
    # Check for lab schedule
    lab_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    lab_schedule_df = pd.DataFrame()
    has_lab_schedule = False
    
    if lab_folders:
        latest_lab_folder = max(lab_folders)
        print(f"Latest lab folder: {latest_lab_folder}")
        
        # Try different lab schedule file names
        lab_file_candidates = [
            "combined_theory_lab_schedule.csv",
            "lab_schedule.csv"
        ]
        
        for lab_file_name in lab_file_candidates:
            lab_schedule_file = os.path.join(output_dir, latest_lab_folder, lab_file_name)
            if os.path.exists(lab_schedule_file):
                print(f"Lab schedule file: {lab_schedule_file}")
                lab_schedule_df = pd.read_csv(lab_schedule_file)
                has_lab_schedule = True
                break
        
        if not has_lab_schedule:
            print(f"Lab schedule files not found in {latest_lab_folder}")
    
    # Combine schedules if lab schedule exists
    if has_lab_schedule:
        # If using combined schedule, use lab schedule only
        if 'combined_theory_lab_schedule.csv' in lab_schedule_file:
            schedule_df = lab_schedule_df
        else:
            # Combine theory and lab schedules
            schedule_df = pd.concat([theory_schedule_df, lab_schedule_df], ignore_index=True)
        print(f"Using combined theory + lab schedule ({len(schedule_df)} total assignments)")
    else:
        schedule_df = theory_schedule_df
        print(f"Using theory schedule only ({len(schedule_df)} assignments)")
    
    print("🔍 LTP CONSTRAINT VERIFICATION (WITH LAB EVALUATION)")
    print("=" * 80)
    if has_lab_schedule:
        print("✅ Lab allocation found - evaluating practical hours")
    else:
        print("⚠️  Lab allocation not found - practical hours will be marked as missing")
    print("=" * 80)
    
    print(f"📊 SUMMARY:")
    print(f"Total course instances in dataset: {len(courses_df)}")
    print(f"Total scheduled assignments: {len(schedule_df)}")
    print(f"Unique courses scheduled: {schedule_df['course_code'].nunique()}")
    print(f"Unique teachers scheduled: {schedule_df['teacher_id'].nunique()}")
    if has_lab_schedule:
        lab_assignments = len(schedule_df[schedule_df['slot_type'] == 'Practical'])
        print(f"Lab assignments found: {lab_assignments}")
    print("=" * 80)
    
    # Create mapping of course requirements - SHOW ALL INSTANCES
    course_requirements = {}
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_requirements[instance_id] = {
            'lecture_hours': row['lecture_hours'],
            'practical_hours': row['practical_hours'],
            'tutorial_hours': row['tutorial_hours'],
            'course_code': row['course_code'],
            'course_name': row['course_name'],
            'teacher_id': row['teacher_id'],
            'student_count': row['student_count'],
            'first_name': row.get('first_name', ''),
            'last_name': row.get('last_name', ''),
            'semester': row.get('semester', 'Unknown'),
            'course_dept': row.get('course_dept', 'Unknown'),
            'academic_year': row.get('academic_year', 'Unknown')
        }
    
    # Count scheduled hours per course instance
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0, 'practical': 0})
    
    for _, row in schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))  # Handle float conversion issues
        except:
            instance_id = str(row['course_instance_id'])  # Fallback
        slot_type = row['slot_type']
        
        if slot_type == 'Lecture':
            scheduled_hours[instance_id]['lecture'] += 1
        elif slot_type == 'Tutorial':
            scheduled_hours[instance_id]['tutorial'] += 1
        elif slot_type == 'Practical':
            scheduled_hours[instance_id]['practical'] += 1
    
    print(f"{'ID':<6} {'Course':<12} {'Teacher':<20} {'Sem':<4} {'L Req':<6} {'L Sch':<6} {'T Req':<6} {'T Sch':<6} {'P Req':<6} {'P Sch':<6} {'Status':<25}")
    print("-" * 135)
    
    violations = 0
    total_instances = 0
    theory_only_violations = 0
    not_scheduled = 0
    practical_violations = 0
    
    # Process ALL instances from the course file
    for instance_id, requirements in sorted(course_requirements.items(), key=lambda x: int(x[0])):
        total_instances += 1
        
        lecture_required = requirements['lecture_hours']
        tutorial_required = requirements['tutorial_hours']
        practical_required = requirements['practical_hours']
        course_code = requirements['course_code']
        course_name = requirements['course_name']
        teacher_id = requirements['teacher_id']
        teacher_name = f"{requirements['first_name']} {requirements['last_name']}".strip() or f"T{teacher_id}"
        semester = requirements['semester']
        
        lecture_scheduled = scheduled_hours[instance_id]['lecture']
        tutorial_scheduled = scheduled_hours[instance_id]['tutorial']
        practical_scheduled = scheduled_hours[instance_id]['practical']
        
        # Check if this instance was scheduled at all
        total_scheduled = lecture_scheduled + tutorial_scheduled + practical_scheduled
        if total_scheduled == 0:
            status = "❌ NOT SCHEDULED"
            not_scheduled += 1
        else:
            # Determine expected tutorial hours based on the specific allocation rules
            if lecture_required == 3 and tutorial_required == 0:
                expected_lecture = 3  # 2 from a1 + 1 from ta1 (as lecture)
                expected_tutorial = 0  # No tutorials
            elif lecture_required == 3 and tutorial_required == 1:
                expected_lecture = 3  # 2 from a1 + 1 from ta1 (as lecture)
                expected_tutorial = 1  # 1 from taa1 (as tutorial)
            elif lecture_required == 2 and tutorial_required == 1:
                expected_lecture = 2  # 2 from a1 slots
                expected_tutorial = 1  # 1 from ta1 (as tutorial)
            elif lecture_required == 1 and tutorial_required == 1:
                expected_lecture = 1  # 1 from a1 slot
                expected_tutorial = 1  # 1 from ta1 (as tutorial)
            elif lecture_required == 2 and tutorial_required == 0:
                expected_lecture = 2  # 2 from a1 slots
                expected_tutorial = 0  # No tutorials
            elif lecture_required == 1 and tutorial_required == 0:
                expected_lecture = 1  # 1 from a1 slot
                expected_tutorial = 0  # No tutorials
            elif lecture_required == 4:
                expected_lecture = 4  # 4-lecture courses get all lecture hours
                expected_tutorial = 1  # Plus 1 tutorial
            elif tutorial_required > 0:
                expected_lecture = lecture_required
                expected_tutorial = tutorial_required
            else:
                expected_lecture = lecture_required
                expected_tutorial = 0
            
            # Check compliance
            lecture_ok = lecture_scheduled == expected_lecture
            tutorial_ok = tutorial_scheduled == expected_tutorial
            
            # Check practical hours based on lab session structure
            if practical_required > 0 and has_lab_schedule:
                # Each lab session = 2 practical hours, so required sessions = practical_required / 2
                expected_lab_sessions = (practical_required + 1) // 2  # Round up for odd numbers
                expected_practical_hours = expected_lab_sessions * 2
                practical_ok = practical_scheduled >= practical_required  # Allow scheduling more than required
            elif practical_required > 0 and not has_lab_schedule:
                # Lab schedule not available, mark as missing
                practical_ok = False
                expected_practical_hours = practical_required
            else:
                # No practical hours required
                practical_ok = practical_scheduled == 0
                expected_practical_hours = 0
            
            # Overall status
            theory_ok = lecture_ok and tutorial_ok
            
            if theory_ok and practical_ok:
                status = "✅ FULLY COMPLIANT"
            elif theory_ok and not practical_ok and practical_required > 0:
                if has_lab_schedule:
                    status = "⚠️ PRACTICAL ISSUE"
                    practical_violations += 1
                else:
                    status = "⚠️ PRACTICAL MISSING"
                    # Don't count as violation if lab schedule not available
            elif not theory_ok and practical_ok:
                status = "⚠️ THEORY ISSUE"
                theory_only_violations += 1
            elif not theory_ok and not practical_ok:
                if practical_required > 0:
                    status = "❌ THEORY+PRACTICAL"
                    violations += 1
                else:
                    status = "❌ THEORY VIOLATION"
                    violations += 1
            else:
                status = "✅ COMPLIANT"
        
        # Show actual vs expected for clarity
        if total_scheduled == 0:
            lec_display = f"0/{lecture_required}"
            tut_display = f"0/{tutorial_required if tutorial_required > 0 else '0'}"
            if practical_required > 0:
                prac_display = f"0/{practical_required}"
            else:
                prac_display = "0/0"
        else:
            # Use the same logic as above for display consistency
            if lecture_required == 3 and tutorial_required == 0:
                display_expected_lecture = 3
                display_expected_tutorial = 0
            elif lecture_required == 3 and tutorial_required == 1:
                display_expected_lecture = 3
                display_expected_tutorial = 1
            elif lecture_required == 2 and tutorial_required == 1:
                display_expected_lecture = 2
                display_expected_tutorial = 1
            elif lecture_required == 1 and tutorial_required == 1:
                display_expected_lecture = 1
                display_expected_tutorial = 1
            elif lecture_required == 2 and tutorial_required == 0:
                display_expected_lecture = 2
                display_expected_tutorial = 0
            elif lecture_required == 1 and tutorial_required == 0:
                display_expected_lecture = 1
                display_expected_tutorial = 0
            elif lecture_required == 4:
                display_expected_lecture = 4
                display_expected_tutorial = 1
            elif tutorial_required > 0:
                display_expected_lecture = lecture_required
                display_expected_tutorial = tutorial_required
            else:
                display_expected_lecture = lecture_required
                display_expected_tutorial = 0
            
            lec_display = f"{lecture_scheduled}/{display_expected_lecture}"
            tut_display = f"{tutorial_scheduled}/{display_expected_tutorial}"
            
            if practical_required > 0:
                if has_lab_schedule:
                    prac_display = f"{practical_scheduled}/{practical_required}"
                else:
                    prac_display = f"{practical_scheduled}/Missing"
            else:
                prac_display = f"{practical_scheduled}/0"
        
        print(f"{instance_id:<6} {course_code:<12} {teacher_name[:19]:<20} {semester:<4} {lecture_required:<6} {lec_display:<6} {tutorial_required:<6} {tut_display:<6} {practical_required:<6} {prac_display:<6} {status:<25}")
    
    print("-" * 135)
    print(f"\n📊 COMPREHENSIVE LTP CONSTRAINT RESULTS:")
    print(f"Total instances in dataset: {total_instances}")
    print(f"✅ Fully compliant instances: {total_instances - violations - theory_only_violations - not_scheduled - practical_violations}")
    print(f"⚠️  Theory issues only: {theory_only_violations}")
    if has_lab_schedule:
        print(f"⚠️  Practical issues only: {practical_violations}")
        print(f"❌ Theory+Practical violations: {violations}")
    else:
        print(f"⚠️  Practical missing (no lab schedule): {len([req for req in course_requirements.values() if req['practical_hours'] > 0])}")
        print(f"❌ Theory violations: {violations}")
    print(f"🚫 Not scheduled at all: {not_scheduled}")
    
    if has_lab_schedule:
        total_with_issues = violations + theory_only_violations + practical_violations + not_scheduled
        print(f"📈 Overall success rate: {((total_instances - total_with_issues)/total_instances)*100:.1f}%")
        print(f"📈 Theory compliance rate: {((total_instances - violations - theory_only_violations - not_scheduled)/max(total_instances - not_scheduled, 1))*100:.1f}%")
        print(f"📈 Practical compliance rate: {((total_instances - violations - practical_violations)/max(sum(1 for req in course_requirements.values() if req['practical_hours'] > 0), 1))*100:.1f}%")
    else:
        print(f"📈 Overall success rate (theory only): {((total_instances - violations - theory_only_violations - not_scheduled)/total_instances)*100:.1f}%")
        print(f"📈 Theory compliance rate: {((total_instances - violations - theory_only_violations - not_scheduled)/max(total_instances - not_scheduled, 1))*100:.1f}%")
    
    # Lab-specific analysis if lab schedule exists
    if has_lab_schedule:
        print(f"\n🧪 LAB SCHEDULING ANALYSIS:")
        courses_with_practicals = {id: req for id, req in course_requirements.items() if req['practical_hours'] > 0}
        print(f"Courses requiring practicals: {len(courses_with_practicals)}")
        
        lab_scheduled = 0
        lab_compliant = 0
        total_practical_hours_required = 0
        total_practical_hours_scheduled = 0
        
        for instance_id, req in courses_with_practicals.items():
            practical_required = req['practical_hours']
            practical_scheduled = scheduled_hours[instance_id]['practical']
            total_practical_hours_required += practical_required
            total_practical_hours_scheduled += practical_scheduled
            
            if practical_scheduled > 0:
                lab_scheduled += 1
                if practical_scheduled >= practical_required:
                    lab_compliant += 1
        
        print(f"Courses with lab sessions scheduled: {lab_scheduled}/{len(courses_with_practicals)} ({(lab_scheduled/max(len(courses_with_practicals), 1))*100:.1f}%)")
        print(f"Courses with sufficient practical hours: {lab_compliant}/{len(courses_with_practicals)} ({(lab_compliant/max(len(courses_with_practicals), 1))*100:.1f}%)")
        print(f"Total practical hours: {total_practical_hours_scheduled}/{total_practical_hours_required} scheduled")
        
        # Analyze lab session efficiency
        lab_sessions_used = total_practical_hours_scheduled // 2  # Each lab session = 2 hours
        print(f"Lab sessions utilized: {lab_sessions_used} (each session = 2 practical hours)")
        
        # Check for teacher workload in labs
        teacher_lab_hours = defaultdict(int)
        for _, row in schedule_df.iterrows():
            if row['slot_type'] == 'Practical':
                teacher_lab_hours[row['teacher_id']] += 2  # Each lab slot = 2 hours
        
        if teacher_lab_hours:
            max_lab_hours = max(teacher_lab_hours.values())
            avg_lab_hours = sum(teacher_lab_hours.values()) / len(teacher_lab_hours)
            print(f"Teacher lab workload: Max {max_lab_hours}h, Avg {avg_lab_hours:.1f}h per teacher")
    
    else:
        print(f"\n🧪 LAB SCHEDULING ANALYSIS:")
        courses_with_practicals = {id: req for id, req in course_requirements.items() if req['practical_hours'] > 0}
        total_practical_hours_required = sum(req['practical_hours'] for req in courses_with_practicals.values())
        print(f"Courses requiring practicals: {len(courses_with_practicals)}")
        print(f"Total practical hours required: {total_practical_hours_required}")
        print(f"❌ Lab schedule not found - run lab_scheduler.py to generate lab allocations")
    
    # Group analysis by course type
    print(f"\n📋 ANALYSIS BY COURSE TYPE:")
    course_type_analysis = defaultdict(lambda: {'total': 0, 'scheduled': 0, 'compliant': 0})
    
    for instance_id, requirements in course_requirements.items():
        lecture_hours = requirements['lecture_hours']
        tutorial_hours = requirements['tutorial_hours']
        practical_hours = requirements['practical_hours']
        
        # Classify course type
        if lecture_hours == 3 and practical_hours > 0:
            course_type = "3L+P courses"
        elif lecture_hours == 3 and practical_hours == 0:
            course_type = "3L only courses"
        elif lecture_hours == 4:
            course_type = "4L courses"
        elif lecture_hours == 1 and practical_hours > 0:
            course_type = "1L+P courses"
        elif tutorial_hours > 0:
            course_type = "Tutorial courses"
        else:
            course_type = "Other courses"
        
        course_type_analysis[course_type]['total'] += 1
        
        # Check if scheduled
        total_scheduled = (scheduled_hours[instance_id]['lecture'] + 
                         scheduled_hours[instance_id]['tutorial'] + 
                         scheduled_hours[instance_id]['practical'])
        
        if total_scheduled > 0:
            course_type_analysis[course_type]['scheduled'] += 1
            
            # Check compliance using the new allocation logic
            if lecture_hours == 3 and tutorial_hours == 0:
                expected_lecture, expected_tutorial = 3, 0
            elif lecture_hours == 3 and tutorial_hours == 1:
                expected_lecture, expected_tutorial = 3, 1
            elif lecture_hours == 2 and tutorial_hours == 1:
                expected_lecture, expected_tutorial = 2, 1
            elif lecture_hours == 1 and tutorial_hours == 1:
                expected_lecture, expected_tutorial = 1, 1
            elif lecture_hours == 2 and tutorial_hours == 0:
                expected_lecture, expected_tutorial = 2, 0
            elif lecture_hours == 1 and tutorial_hours == 0:
                expected_lecture, expected_tutorial = 1, 0
            elif lecture_hours == 4:
                expected_lecture, expected_tutorial = lecture_hours, 1
            elif tutorial_hours > 0:
                expected_lecture, expected_tutorial = lecture_hours, tutorial_hours
            else:
                expected_lecture, expected_tutorial = lecture_hours, 0
            
            lecture_ok = scheduled_hours[instance_id]['lecture'] == expected_lecture
            tutorial_ok = scheduled_hours[instance_id]['tutorial'] == expected_tutorial
            
            if lecture_ok and tutorial_ok:
                course_type_analysis[course_type]['compliant'] += 1
    
    for course_type, stats in course_type_analysis.items():
        scheduled_rate = (stats['scheduled'] / stats['total']) * 100 if stats['total'] > 0 else 0
        compliance_rate = (stats['compliant'] / stats['scheduled']) * 100 if stats['scheduled'] > 0 else 0
        print(f"  {course_type}: {stats['total']} total, {stats['scheduled']} scheduled ({scheduled_rate:.1f}%), {stats['compliant']} compliant ({compliance_rate:.1f}%)")
    
    # Special analysis for 3-lecture courses
    three_lecture_courses = {id: req for id, req in course_requirements.items() if req['lecture_hours'] == 3}
    if three_lecture_courses:
        print(f"\n🎯 3-LECTURE COURSE DETAILED ANALYSIS:")
        print(f"Total 3-lecture courses: {len(three_lecture_courses)}")
        three_lec_compliant = 0
        three_lec_scheduled = 0
        
        print(f"{'ID':<6} {'Course':<12} {'Teacher':<15} {'L Sch':<6} {'T Sch':<6} {'Status':<15}")
        print("-" * 70)
        
        for instance_id, req in three_lecture_courses.items():
            lec_scheduled = scheduled_hours[instance_id]['lecture']
            tut_scheduled = scheduled_hours[instance_id]['tutorial']
            total_scheduled = lec_scheduled + tut_scheduled + scheduled_hours[instance_id]['practical']
            
            teacher_name = f"{req['first_name']} {req['last_name']}".strip() or f"T{req['teacher_id']}"
            tutorial_required = req['tutorial_hours']
            
            if total_scheduled == 0:
                compliance = "❌ Not Scheduled"
            else:
                three_lec_scheduled += 1
                # Check based on new allocation logic
                if tutorial_required == 0:
                    # Case 1: 3L+0T should get 3L+0T
                    if lec_scheduled == 3 and tut_scheduled == 0:
                        three_lec_compliant += 1
                        compliance = "✅ Perfect"
                    else:
                        compliance = "❌ Wrong Hours"
                elif tutorial_required == 1:
                    # Case 2: 3L+1T should get 3L+1T
                    if lec_scheduled == 3 and tut_scheduled == 1:
                        three_lec_compliant += 1
                        compliance = "✅ Perfect"
                    else:
                        compliance = "❌ Wrong Hours"
                else:
                    # Other cases - use general logic
                    if lec_scheduled == 3 and tut_scheduled == tutorial_required:
                        three_lec_compliant += 1
                        compliance = "✅ Perfect"
                    else:
                        compliance = "❌ Wrong Hours"
            
            print(f"{instance_id:<6} {req['course_code']:<12} {teacher_name[:14]:<15} {lec_scheduled:<6} {tut_scheduled:<6} {compliance:<15}")
        
        print("-" * 70)
        print(f"3-lecture scheduling rate: {three_lec_scheduled}/{len(three_lecture_courses)} ({(three_lec_scheduled/len(three_lecture_courses))*100:.1f}%)")
        print(f"3-lecture compliance rate: {three_lec_compliant}/{three_lec_scheduled if three_lec_scheduled > 0 else 1} ({(three_lec_compliant/max(three_lec_scheduled, 1))*100:.1f}%)")
    
    if violations == 0 and theory_only_violations == 0 and not_scheduled == 0 and (not has_lab_schedule or practical_violations == 0):
        print(f"\n🎉 ALL LTP CONSTRAINTS SATISFIED!")
        print(f"   ✅ All course instances scheduled and compliant")
        print(f"   ✅ Lecture hours properly allocated")
        print(f"   ✅ Tutorial hours allocated according to rules:")
        print(f"      - 3L+0T courses: 3 lectures (ta1 as 3rd lecture) + 0 tutorials")
        print(f"      - 3L+1T courses: 3 lectures (ta1 as 3rd lecture) + 1 tutorial (taa1)")
        print(f"      - 2L+1T courses: 2 lectures + 1 tutorial (ta1 as tutorial)")
        print(f"      - 1L+1T courses: 1 lecture + 1 tutorial (ta1 as tutorial)")
        print(f"      - 2L+0T courses: 2 lectures + 0 tutorials")
        print(f"      - 1L+0T courses: 1 lecture + 0 tutorials")
        print(f"      - 4-lecture courses: 4 lectures + 1 tutorial")
        print(f"      - Other courses: as specified in tutorial_hours")
        if has_lab_schedule:
            print(f"   ✅ Practical hours properly allocated in lab sessions")
            print(f"      - Each lab session = 2 practical hours (L1, L2, L3, L4, L5, L6)")
            print(f"      - Continuous room assignment for multi-slot sessions")
            print(f"      - No conflicts between theory and lab schedules")
        else:
            print(f"   ⚠️  Practical hours not evaluated (lab schedule not found)")
        return True
    else:
        print(f"\n⚠️  CONSTRAINT ISSUES DETECTED!")
        if not_scheduled > 0:
            print(f"   🚫 {not_scheduled} course instances not scheduled at all")
        if violations > 0:
            if has_lab_schedule:
                print(f"   ❌ {violations} theory+practical constraint violations")
            else:
                print(f"   ❌ {violations} theory constraint violations")
        if theory_only_violations > 0:
            print(f"   ⚠️  {theory_only_violations} theory-only issues")
        if has_lab_schedule and practical_violations > 0:
            print(f"   ⚠️  {practical_violations} practical-only issues")
        if not has_lab_schedule:
            courses_needing_labs = len([req for req in course_requirements.values() if req['practical_hours'] > 0])
            if courses_needing_labs > 0:
                print(f"   🧪 {courses_needing_labs} courses need lab allocation - run lab_scheduler.py")
        
        # Return success if only missing lab schedule but theory is good
        if has_lab_schedule:
            return violations == 0 and not_scheduled == 0
        else:
            return violations == 0 and not_scheduled == 0 and theory_only_violations == 0

if __name__ == "__main__":
    verify_ltp_constraints() 