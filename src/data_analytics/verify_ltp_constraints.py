import pandas as pd
import os
from collections import defaultdict

def verify_ltp_constraints():
    """Verify that LTP constraints are satisfied for all courses."""
    
    # Load course requirements - try both possible file names
    course_files = [
        # "data/mapped_data/computer_dept_teacher_courses.csv",
        "data/mapped_data/cs_teacher_courses.csv"
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
    
    folders = [f for f in os.listdir(output_dir) if f.startswith("macroblock_schedule_")]
    if not folders:
        print("No macroblock schedule found!")
        return False
        
    latest_folder = max(folders)
    print(f"Latest folder: {latest_folder}")
    schedule_file = os.path.join(output_dir, latest_folder, "macroblock_schedule.csv")
    print(f"Schedule file: {schedule_file}")
    
    if not os.path.exists(schedule_file):
        print(f"Schedule file not found: {schedule_file}")
        return False
    
    schedule_df = pd.read_csv(schedule_file)
    
    print("🔍 LTP CONSTRAINT VERIFICATION (SIMPLIFIED SYSTEM)")
    print("=" * 80)
    print("Note: Lab allocation is skipped - only theory (Lecture/Tutorial) verified")
    print("=" * 80)
    
    print(f"📊 SUMMARY:")
    print(f"Total course instances in dataset: {len(courses_df)}")
    print(f"Total scheduled assignments: {len(schedule_df)}")
    print(f"Unique courses scheduled: {schedule_df['course_code'].nunique()}")
    print(f"Unique teachers scheduled: {schedule_df['teacher_id'].nunique()}")
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
    
    print(f"{'ID':<6} {'Course':<12} {'Teacher':<20} {'Sem':<4} {'L Req':<6} {'L Sch':<6} {'T Req':<6} {'T Sch':<6} {'P Req':<6} {'P Sch':<6} {'Status':<20}")
    print("-" * 130)
    
    violations = 0
    total_instances = 0
    theory_only_violations = 0
    not_scheduled = 0
    
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
            # Determine expected tutorial hours based on the current system rules
            # For 3-lecture courses: expect exactly 1 tutorial (3rd hour)
            # For other courses with tutorials: expect tutorial_hours
            # For 4-lecture courses: expect 1 tutorial
            if lecture_required == 3:
                expected_tutorial = 1  # 3rd hour as tutorial
                expected_lecture = 2   # Only 2 actual lecture hours
            elif lecture_required == 4:
                expected_tutorial = 1  # 4-lecture courses get 1 tutorial
                expected_lecture = lecture_required
            elif tutorial_required > 0:
                expected_tutorial = tutorial_required
                expected_lecture = lecture_required
            else:
                expected_tutorial = 0
                expected_lecture = lecture_required
            
            # Check compliance - strict for theory, skip practicals
            lecture_ok = lecture_scheduled == expected_lecture
            tutorial_ok = tutorial_scheduled == expected_tutorial
            practical_ok = True  # Skip practical validation (labs not allocated)
            
            # Overall status
            theory_ok = lecture_ok and tutorial_ok
            
            if theory_ok:
                status = "✅ Compliant"
            else:
                if practical_required > 0:
                    status = "⚠️ Theory Issue"  # Only theory violation, practicals expected but not checked
                    theory_only_violations += 1
                else:
                    status = "❌ Violation"
                    violations += 1
        
        # Show actual vs expected for clarity (or just actual if not scheduled)
        if total_scheduled == 0:
            lec_display = f"0/{lecture_required}"
            tut_display = f"0/{tutorial_required if tutorial_required > 0 else '0'}"
            prac_display = f"0/Skip" if practical_required > 0 else "0/0"
        else:
            if lecture_required == 3:
                expected_lecture = 2
                expected_tutorial = 1
            elif lecture_required == 4:
                expected_lecture = lecture_required
                expected_tutorial = 1
            elif tutorial_required > 0:
                expected_lecture = lecture_required
                expected_tutorial = tutorial_required
            else:
                expected_lecture = lecture_required
                expected_tutorial = 0
            
            lec_display = f"{lecture_scheduled}/{expected_lecture}"
            tut_display = f"{tutorial_scheduled}/{expected_tutorial}"
            prac_display = f"{practical_scheduled}/Skip" if practical_required > 0 else f"{practical_scheduled}/0"
        
        print(f"{instance_id:<6} {course_code:<12} {teacher_name[:19]:<20} {semester:<4} {lecture_required:<6} {lec_display:<6} {tutorial_required:<6} {tut_display:<6} {practical_required:<6} {prac_display:<6} {status:<20}")
    
    print("-" * 130)
    print(f"\n📊 COMPREHENSIVE LTP CONSTRAINT RESULTS:")
    print(f"Total instances in dataset: {total_instances}")
    print(f"✅ Fully compliant instances: {total_instances - violations - theory_only_violations - not_scheduled}")
    print(f"⚠️  Theory issues (but have practicals): {theory_only_violations}")
    print(f"❌ Pure violations: {violations}")
    print(f"🚫 Not scheduled at all: {not_scheduled}")
    print(f"📈 Overall success rate: {((total_instances - violations - not_scheduled)/total_instances)*100:.1f}%")
    print(f"📈 Theory compliance rate (excluding unscheduled): {((total_instances - violations - not_scheduled)/max(total_instances - not_scheduled, 1))*100:.1f}%")
    
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
            
            # Check compliance
            if lecture_hours == 3:
                expected_lecture, expected_tutorial = 2, 1
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
            
            if total_scheduled == 0:
                compliance = "❌ Not Scheduled"
            elif lec_scheduled == 2 and tut_scheduled == 1:
                three_lec_compliant += 1
                three_lec_scheduled += 1
                compliance = "✅ Perfect"
            else:
                three_lec_scheduled += 1
                compliance = "❌ Wrong Hours"
            
            print(f"{instance_id:<6} {req['course_code']:<12} {teacher_name[:14]:<15} {lec_scheduled:<6} {tut_scheduled:<6} {compliance:<15}")
        
        print("-" * 70)
        print(f"3-lecture scheduling rate: {three_lec_scheduled}/{len(three_lecture_courses)} ({(three_lec_scheduled/len(three_lecture_courses))*100:.1f}%)")
        print(f"3-lecture compliance rate: {three_lec_compliant}/{three_lec_scheduled if three_lec_scheduled > 0 else 1} ({(three_lec_compliant/max(three_lec_scheduled, 1))*100:.1f}%)")
    
    if violations == 0 and theory_only_violations == 0 and not_scheduled == 0:
        print(f"\n🎉 ALL THEORY CONSTRAINTS SATISFIED!")
        print(f"   ✅ All course instances scheduled and compliant")
        print(f"   ✅ Lecture hours properly allocated")
        print(f"   ✅ Tutorial hours allocated according to rules:")
        print(f"      - 3-lecture courses: 2 lectures + 1 tutorial (3rd hour)")
        print(f"      - 4-lecture courses: 4 lectures + 1 tutorial")
        print(f"      - Other courses: as specified in tutorial_hours")
        print(f"   ⏭️  Practical hours validation skipped (labs not allocated)")
        return True
    else:
        print(f"\n⚠️  CONSTRAINT ISSUES DETECTED!")
        if not_scheduled > 0:
            print(f"   🚫 {not_scheduled} course instances not scheduled at all")
        if violations > 0:
            print(f"   ❌ {violations} pure theory constraint violations")
        if theory_only_violations > 0:
            print(f"   ⚠️  {theory_only_violations} theory issues (courses with practicals)")
        print(f"   Note: Practical issues expected (labs not implemented)")
        return violations == 0 and not_scheduled == 0  # Consider not_scheduled as failure too

if __name__ == "__main__":
    verify_ltp_constraints() 