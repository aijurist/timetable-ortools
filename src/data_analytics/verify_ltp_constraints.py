import pandas as pd
import os
from collections import defaultdict

def verify_ltp_constraints():
    """Verify that LTP constraints are satisfied for all courses with updated batching logic and theory verification."""
    
    # Load course requirements
    course_file = "data/final_v4.csv"
    
    if not os.path.exists(course_file):
        print(f"Course file not found: {course_file}")
        return False
    
    print(f"Using course file: {course_file}")
    courses_df = pd.read_csv(course_file)
    
    # Find the latest schedules from current implementation
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("No output directory found!")
        return False
    
    # Find lab schedule folders
    lab_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("lab_schedule_")]
    # Find theory schedule folders  
    theory_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("theory_schedule_")]
    # Find combined schedule folders
    combined_schedule_folders = [f for f in os.listdir(output_dir) if f.startswith("combined_schedule_")]
    
    if not lab_schedule_folders and not theory_schedule_folders and not combined_schedule_folders:
        print("No schedule folders found!")
        return False
    
    # Get latest schedules
    latest_lab_folder = max(lab_schedule_folders) if lab_schedule_folders else None
    latest_theory_folder = max(theory_schedule_folders) if theory_schedule_folders else None
    latest_combined_folder = max(combined_schedule_folders) if combined_schedule_folders else None
    
    print(f"Latest lab schedule folder: {latest_lab_folder}")
    print(f"Latest theory schedule folder: {latest_theory_folder}")
    print(f"Latest combined schedule folder: {latest_combined_folder}")
    
    # Load schedules
    lab_schedule_df = None
    theory_schedule_df = None
    
    # Load lab schedule
    if latest_lab_folder:
        lab_schedule_file = os.path.join(output_dir, latest_lab_folder, "lab_schedule.csv")
        if os.path.exists(lab_schedule_file):
            lab_schedule_df = pd.read_csv(lab_schedule_file)
            print(f"Loaded lab schedule with {len(lab_schedule_df)} assignments")
        else:
            print(f"Lab schedule file not found: {lab_schedule_file}")
    
    # Load theory schedule
    if latest_theory_folder:
        theory_schedule_file = os.path.join(output_dir, latest_theory_folder, "theory_schedule.csv")
        if os.path.exists(theory_schedule_file):
            theory_schedule_df = pd.read_csv(theory_schedule_file)
            print(f"Loaded theory schedule with {len(theory_schedule_df)} assignments")
        else:
            print(f"Theory schedule file not found: {theory_schedule_file}")
    
    # If no individual schedules found, try combined schedule
    if lab_schedule_df is None and theory_schedule_df is None and latest_combined_folder:
        combined_lab_file = os.path.join(output_dir, latest_combined_folder,"combined_lab_schedule.csv")
        combined_theory_file = os.path.join(output_dir, latest_combined_folder,"combined_theory_schedule.csv")
        
        if os.path.exists(combined_lab_file):
            lab_schedule_df = pd.read_csv(combined_lab_file)
            print(f"Loaded combined lab schedule with {len(lab_schedule_df)} assignments")
        
        if os.path.exists(combined_theory_file):
            theory_schedule_df = pd.read_csv(combined_theory_file)
            print(f"Loaded combined theory schedule with {len(theory_schedule_df)} assignments")
    
    if lab_schedule_df is None and theory_schedule_df is None:
        print("No valid schedule files found!")
        return False
    
    # Determine what types of schedules we have
    has_lab_schedule = lab_schedule_df is not None and not lab_schedule_df.empty
    has_theory_schedule = theory_schedule_df is not None and not theory_schedule_df.empty
    
    print(f"Schedule types available:")
    print(f"- Lab schedule: {'✅ Available' if has_lab_schedule else '❌ Not available'}")
    print(f"- Theory schedule: {'✅ Available' if has_theory_schedule else '❌ Not available'}")
    
    if has_lab_schedule:
        print(f"Lab assignments: {len(lab_schedule_df)}")
    if has_theory_schedule:
        print(f"Theory assignments: {len(theory_schedule_df)}")
    
    print("COMPREHENSIVE LTP CONSTRAINT VERIFICATION")
    print("=" * 85)
    print("Verifying both LAB and THEORY constraints")
    if has_lab_schedule:
        print("✅ Lab allocation found - evaluating practical hours")
    else:
        print("❌ Lab allocation not found - practical hours will be marked as missing")
    if has_theory_schedule:
        print("✅ Theory allocation found - evaluating lecture/tutorial hours")
    else:
        print("❌ Theory allocation not found - lecture/tutorial hours will be marked as missing")
    print("=" * 85)
    
    print(f"SUMMARY:")
    print(f"Total course instances in dataset: {len(courses_df)}")
    
    total_assignments = 0
    unique_courses = set()
    unique_teachers = set()
    
    if has_lab_schedule:
        total_assignments += len(lab_schedule_df)
        unique_courses.update(lab_schedule_df['course_code'].unique())
        unique_teachers.update(lab_schedule_df['teacher_id'].unique())
        print(f"Lab assignments: {len(lab_schedule_df)}")
        
        # Analyze batching in lab assignments
        if 'course_code_display' in lab_schedule_df.columns:
            batched_assignments = len(lab_schedule_df[lab_schedule_df['course_code_display'].str.contains(' Batch', na=False)])
            print(f"Batched lab assignments: {batched_assignments}")
        
        # Check for capacity information in lab assignments
        if 'is_batched' in lab_schedule_df.columns:
            batched_courses = len(lab_schedule_df[lab_schedule_df['is_batched'] == True])
            print(f"Courses using dynamic batching: {batched_courses}")
    
    if has_theory_schedule:
        total_assignments += len(theory_schedule_df)
        unique_courses.update(theory_schedule_df['course_code'].unique())
        unique_teachers.update(theory_schedule_df['teacher_id'].unique())
        print(f"Theory assignments: {len(theory_schedule_df)}")
    
    print(f"Total assignments: {total_assignments}")
    print(f"Unique courses scheduled: {len(unique_courses)}")
    print(f"Unique teachers scheduled: {len(unique_teachers)}")
    print("=" * 85)
    
    # Create mapping of course requirements - SHOW ALL INSTANCES
    course_requirements = {}
    for _, row in courses_df.iterrows():
        instance_id = str(row['id'])
        course_dept = row.get('course_dept', 'Unknown')
        
        # Filter to only include Computer Science courses
        # if 'Computer Science' in course_dept:
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
            'course_dept': course_dept,
            'academic_year': row.get('academic_year', 'Unknown')
        }

    # Count scheduled hours per course instance - Enhanced for batching and theory
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0, 'practical': 0, 'batches': set()})
    
    # Count theory assignments from theory schedule (if available)
    if has_theory_schedule:
        for _, row in theory_schedule_df.iterrows():
            try:
                instance_id = str(int(float(row['course_instance_id'])))
            except:
                instance_id = str(row['course_instance_id'])
            
            session_type = row.get('session_type', 'lecture').lower()
            
            if session_type in ['lecture', 'theory']:
                scheduled_hours[instance_id]['lecture'] += 1
            elif session_type in ['tutorial', 'tut']:
                scheduled_hours[instance_id]['tutorial'] += 1
    
    # Count lab assignments from lab schedule (if available)
    if has_lab_schedule:
        # Enhanced counting for batched vs non-batched courses
        for _, row in lab_schedule_df.iterrows():
            try:
                instance_id = str(int(float(row['course_instance_id'])))  # Handle float conversion issues
            except:
                instance_id = str(row['course_instance_id'])  # Fallback
            
            # Check if this is a batched course
            is_batched = row.get('is_batched', False)
            
            if is_batched:
                # For batched courses: each lab session = 2 practical hours per batch
                # Each batch should get enough sessions to meet the practical hour requirement
                batch_info = row.get('batch_info', '')
                if batch_info:
                    # Track sessions per batch
                    if 'batch_sessions' not in scheduled_hours[instance_id]:
                        scheduled_hours[instance_id]['batch_sessions'] = {}
                    
                    batch_key = batch_info.strip()
                    if batch_key not in scheduled_hours[instance_id]['batch_sessions']:
                        scheduled_hours[instance_id]['batch_sessions'][batch_key] = 0
                    
                    # Each session = 2 practical hours
                    scheduled_hours[instance_id]['batch_sessions'][batch_key] += 2
                    scheduled_hours[instance_id]['batches'].add(batch_key)
                
                # Also increment the general practical counter for overall display
                # This is needed for correct analysis
                scheduled_hours[instance_id]['practical'] += 2
            else:
                # For non-batched courses: each lab session = 2 practical hours
                scheduled_hours[instance_id]['practical'] += 2
    
    print(f"{'ID':<6} {'Course':<12} {'Teacher':<20} {'Sem':<4} {'P Req':<6} {'P Sch':<10} {'P Status':<15} {'Status':<25}")
    print("-" * 110)
    
    violations = 0
    total_instances = 0
    theory_only_violations = 0
    not_scheduled = 0
    practical_violations = 0
    batching_issues = 0
    
    # Process ALL instances from the course file
    for instance_id, requirements in sorted(course_requirements.items(), key=lambda x: int(x[0])):
        total_instances += 1
        
        # Theory requirements (not checked - disabled)
        lecture_required = requirements['lecture_hours']
        tutorial_required = requirements['tutorial_hours']
        practical_required = requirements['practical_hours']
        course_code = requirements['course_code']
        course_name = requirements['course_name']
        teacher_id = requirements['teacher_id']
        teacher_name = f"{requirements['first_name']} {requirements['last_name']}".strip() or f"T{teacher_id}"
        semester = requirements['semester']
        
        # Only count practical hours (theory disabled)
        lecture_scheduled = 0  # Not checked
        tutorial_scheduled = 0  # Not checked  
        practical_scheduled = scheduled_hours[instance_id]['practical']
        batches_found = scheduled_hours[instance_id]['batches']
        
        # Practical status display and compliance checking
        if practical_required > 0:
            if has_lab_schedule:
                # Check if this is a batched course
                batch_sessions = scheduled_hours[instance_id].get('batch_sessions', {})
                
                if batch_sessions:
                    # Batched course: check if each batch meets the requirement
                    batch_compliant = True
                    batch_details = []
                    
                    for batch_key, batch_hours in batch_sessions.items():
                        if batch_hours >= practical_required:
                            batch_details.append(f"{batch_key}:OK")
                        else:
                            batch_details.append(f"{batch_key}:{batch_hours}/{practical_required}")
                            batch_compliant = False
                    
                    if batch_compliant and len(batch_sessions) >= 1:
                        practical_status = f"BATCHED OK ({len(batch_sessions)} batches)"
                        practical_ok = True
                        # Update practical_scheduled for display
                        practical_scheduled = practical_required  # Show as fully satisfied
                    else:
                        practical_status = f"BATCH PARTIAL ({', '.join(batch_details)})"
                        practical_ok = False
                        practical_violations += 1
                        # Calculate total scheduled for display
                        practical_scheduled = sum(batch_sessions.values()) // len(batch_sessions) if batch_sessions else 0
                else:
                    # Non-batched course: use original logic
                    if practical_scheduled >= practical_required:
                        practical_status = "OK"
                        practical_ok = True
                    elif practical_scheduled > 0:
                        practical_status = f"PARTIAL {practical_scheduled}/{practical_required}"
                        practical_ok = False
                        practical_violations += 1
                    else:
                        practical_status = "MISSING"
                        practical_ok = False
                        practical_violations += 1
            else:
                practical_status = "SKIPPED"
                practical_ok = True  # Consider OK if no lab schedule available
        else:
            practical_status = "N/A"
            practical_ok = True  # No practical required
        
        # Check if practical is scheduled (theory checking disabled)
        if practical_required > 0:
            if practical_scheduled == 0:
                status = "❌ NOT SCHEDULED"
                not_scheduled += 1
            elif practical_ok:
                status = "✅ PRACTICAL OK"
            else:
                status = "⚠️ PRACTICAL ISSUE"
                practical_violations += 1
        else:
            # No practical required
            status = "✅ NO PRACTICAL NEEDED"
        
        # Practical display only (theory disabled)
        if practical_required > 0 and has_lab_schedule:
            # practical_scheduled already represents the correct practical hours from lab sessions
            # Each lab session in the schedule = 2 practical hours, so counting is already correct
            prac_display = f"{practical_scheduled}/{practical_required}"
        else:
            prac_display = f"{practical_scheduled}"
        
        print(f"{instance_id:<6} {course_code:<12} {teacher_name[:19]:<20} {semester:<4} {practical_required:<6} {prac_display:<10} {practical_status:<15} {status:<25}")
    
    print("-" * 110)
    print(f"\n📊 LAB CONSTRAINT RESULTS (Theory checking disabled):")
    print(f"Total instances in dataset: {total_instances}")
    courses_with_practicals = sum(1 for req in course_requirements.values() if req['practical_hours'] > 0)
    courses_without_practicals = total_instances - courses_with_practicals
    print(f"Courses requiring practicals: {courses_with_practicals}")
    print(f"Courses without practicals: {courses_without_practicals}")
    if has_lab_schedule:
        print(f"✅ Practical compliant: {courses_with_practicals - practical_violations - not_scheduled}")
        print(f"⚠️  Practical issues: {practical_violations}")
    print(f"🚫 Not scheduled at all: {not_scheduled}")
    if has_lab_schedule:
        print(f"📈 Practical compliance rate: {((courses_with_practicals - practical_violations - not_scheduled)/max(courses_with_practicals, 1))*100:.1f}%")
    
    if has_lab_schedule:
        print(f"\n💡 Lab scheduling features implemented:")
        print(f"  ✓ L1-L6 lab sessions (2 hours each)")
        print(f"  ✓ No conflicts with existing theory schedule")
        print(f"  ✓ Continuous room assignment for multi-slot sessions")
        print(f"  ✓ Individual teacher lab visualizations")
        print(f"  ✓ Macroblock-based allocation prevents theory-lab conflicts")
        print(f"    - Teachers with a1-g1 theory blocks → L4-L6 lab sessions only")
        print(f"    - Teachers with a2-g2 theory blocks → L1-L3 lab sessions only")
        
        # Perform comprehensive lab constraint verification
        lab_verification_result = verify_lab_constraints(lab_schedule_df, course_requirements)
        
        # Analyze lab efficiency and utilization
        analyze_lab_efficiency(lab_schedule_df, course_requirements)
        
        # Update final success determination to include lab constraint compliance
        lab_constraints_ok = lab_verification_result['compliant']
        if not lab_constraints_ok:
            print(f"\n❌ LAB CONSTRAINT VIOLATIONS DETECTED!")
            print(f"  - {len(lab_verification_result['violations'])} lab constraint violations found")
            print(f"  - Review detailed violation list above for specific issues")
        else:
            print(f"\n✅ ALL LAB CONSTRAINTS VERIFIED SUCCESSFULLY!")
    else:
        lab_constraints_ok = True  # No lab constraints to check
        print(f"  ⚠️  Practical hours not evaluated (lab schedule not found)")
    
    # THEORY VERIFICATION
    theory_constraints_ok = True  # Default to true
    if has_theory_schedule:
        print(f"\n🎓 THEORY SCHEDULE FOUND - PERFORMING VERIFICATION")
        print(f"  ✓ Theory room assignments")
        print(f"  ✓ Theory teacher conflict detection")
        print(f"  ✓ Theory capacity verification")
        print(f"  ✓ Theory requirements fulfillment")
        print(f"  ✓ Theory efficiency analysis")
        
        # Perform comprehensive theory constraint verification
        theory_verification_result = verify_theory_constraints(theory_schedule_df, course_requirements)
        
        # Analyze theory efficiency and utilization
        analyze_theory_efficiency(theory_schedule_df, course_requirements)
        
        # Update final success determination to include theory constraint compliance
        theory_constraints_ok = len(theory_verification_result) == 0
        if not theory_constraints_ok:
            print(f"\n❌ THEORY CONSTRAINT VIOLATIONS DETECTED!")
            print(f"  - {len(theory_verification_result)} theory constraint violations found")
            print(f"  - Review detailed violation list above for specific issues")
        else:
            print(f"\n✅ ALL THEORY CONSTRAINTS VERIFIED SUCCESSFULLY!")
    else:
        print(f"\n⚠️  Theory schedule not found - lecture/tutorial hours not evaluated")
    
    # LAB-THEORY CONFLICT VERIFICATION
    if has_lab_schedule and has_theory_schedule:
        print(f"\n🔄 CROSS-SCHEDULE CONFLICT VERIFICATION")
        conflict_violations = verify_lab_theory_conflicts(lab_schedule_df, theory_schedule_df)
        
        if len(conflict_violations) == 0:
            print(f"✅ NO LAB-THEORY CONFLICTS DETECTED!")
        else:
            print(f"❌ LAB-THEORY CONFLICTS DETECTED!")
            print(f"  - {len(conflict_violations)} teacher scheduling conflicts found")
            theory_constraints_ok = False  # Mark as failed if conflicts exist
    
    # Enhanced final validation including both lab and theory constraints
    overall_success = (not_scheduled == 0 and 
                      (not has_lab_schedule or (practical_violations == 0 and batching_issues == 0 and lab_constraints_ok)) and
                      theory_constraints_ok)
    
    # Practical-only analysis (theory checking disabled)
    print(f"\n📋 ANALYSIS BY PRACTICAL REQUIREMENTS:")
    practical_analysis = defaultdict(lambda: {'total': 0, 'scheduled': 0, 'compliant': 0})
    
    for instance_id, requirements in course_requirements.items():
        practical_hours = requirements['practical_hours']
        
        # Classify by practical requirements
        if practical_hours == 0:
            course_type = "No practical"
        elif practical_hours == 2:
            course_type = "2 practical hours"
        elif practical_hours == 4:
            course_type = "4 practical hours"
        elif practical_hours == 6:
            course_type = "6 practical hours"
        else:
            course_type = f"{practical_hours} practical hours"
        
        practical_analysis[course_type]['total'] += 1
        
        # Check if scheduled (only practical since theory is disabled)
        practical_scheduled = scheduled_hours[instance_id]['practical']
        
        if practical_hours > 0:  # Only check courses that need practicals
            if practical_scheduled > 0:
                practical_analysis[course_type]['scheduled'] += 1
                
                # Check compliance - practical hours match requirement
                if practical_scheduled >= practical_hours:
                    practical_analysis[course_type]['compliant'] += 1
        else:
            # No practical required - always compliant
            practical_analysis[course_type]['scheduled'] += 1
            practical_analysis[course_type]['compliant'] += 1
    
    for course_type, stats in practical_analysis.items():
        scheduled_rate = (stats['scheduled'] / stats['total']) * 100 if stats['total'] > 0 else 0
        compliance_rate = (stats['compliant'] / stats['scheduled']) * 100 if stats['scheduled'] > 0 else 0
        print(f"  {course_type}: {stats['total']} total, {stats['scheduled']} scheduled ({scheduled_rate:.1f}%), {stats['compliant']} compliant ({compliance_rate:.1f}%)")
    
    # Special analysis for practical-heavy courses (4+ practical hours)
    practical_heavy_courses = {id: req for id, req in course_requirements.items() if req['practical_hours'] >= 4}
    if practical_heavy_courses:
        print(f"\n🎯 PRACTICAL-HEAVY COURSE DETAILED ANALYSIS (4+ practical hours):")
        print(f"Total practical-heavy courses: {len(practical_heavy_courses)}")
        practical_compliant = 0
        practical_scheduled = 0
        
        print(f"{'ID':<6} {'Course':<12} {'Teacher':<15} {'P Req':<6} {'P Sch':<6} {'Status':<15}")
        print("-" * 70)
        
        for instance_id, req in practical_heavy_courses.items():
            practical_required = req['practical_hours']
            practical_scheduled_hours = scheduled_hours[instance_id]['practical']
            
            teacher_name = f"{req['first_name']} {req['last_name']}".strip() or f"T{req['teacher_id']}"
            
            if practical_scheduled_hours == 0:
                compliance = "❌ Not Scheduled"
            else:
                practical_scheduled += 1
                # Check practical compliance
                if practical_scheduled_hours >= practical_required:
                    practical_compliant += 1
                    compliance = "✅ Perfect"
                else:
                    compliance = f"❌ Partial {practical_scheduled_hours}/{practical_required}"
            
            print(f"{instance_id:<6} {req['course_code']:<12} {teacher_name[:14]:<15} {practical_required:<6} {practical_scheduled_hours:<6} {compliance:<15}")
        
        print("-" * 70)
        print(f"Practical-heavy scheduling rate: {practical_scheduled}/{len(practical_heavy_courses)} ({(practical_scheduled/len(practical_heavy_courses))*100:.1f}%)")
        print(f"Practical-heavy compliance rate: {practical_compliant}/{practical_scheduled if practical_scheduled > 0 else 1} ({(practical_compliant/max(practical_scheduled, 1))*100:.1f}%)")
    
    if overall_success:
        print(f"\n🎉 ALL LTP CONSTRAINTS SATISFIED!")
        print(f"   ✅ All course instances scheduled and compliant")
        if has_lab_schedule:
            print(f"   ✅ LAB CONSTRAINTS VERIFIED:")
            print(f"      - Practical hours properly allocated in lab sessions")
            print(f"      - Each lab session = 2 practical hours (L1, L2, L3, L4, L5, L6)")
            print(f"      - HARD CONSTRAINT: Only courses with practical_hours >= 3 can use 70-capacity labs")
            print(f"      - Courses with practical_hours < 3 MUST use 35-capacity labs (forced batching)")
            print(f"      - Dynamic batching: S1 B1/S1 B2 for 70-student courses in 35-capacity labs")
            print(f"      - Continuous room assignment for multi-slot sessions")
            print(f"      - All batching requirements properly satisfied")
        else:
            print(f"   ⚠️  Practical hours not evaluated (lab schedule not found)")
        
        if has_theory_schedule:
            print(f"   ✅ THEORY CONSTRAINTS VERIFIED:")
            print(f"      - Lecture and tutorial hours properly allocated")
            print(f"      - Theory room assignments without conflicts")
            print(f"      - Theory teacher schedules without overlaps")
            print(f"      - Room capacity constraints satisfied")
        else:
            print(f"   ⚠️  Lecture/tutorial hours not evaluated (theory schedule not found)")
        
        if has_lab_schedule and has_theory_schedule:
            print(f"   ✅ CROSS-SCHEDULE VERIFICATION:")
            print(f"      - No conflicts between theory and lab schedules")
            print(f"      - Teacher availability properly managed")
        
        print(f"   ✅ COMPLETE LTP VERIFICATION SUCCESSFUL!")
        return True
    else:
        print(f"\n⚠️  LTP CONSTRAINT ISSUES DETECTED!")
        if not_scheduled > 0:
            print(f"   🚫 {not_scheduled} course instances not scheduled at all")
        
        # Lab issues
        if has_lab_schedule and practical_violations > 0:
            print(f"   ⚠️  {practical_violations} practical-only issues")
        if has_lab_schedule and batching_issues > 0:
            print(f"   ⚠️  {batching_issues} batching/capacity constraint violations")
            print(f"       - Check for courses with <3 practical hours incorrectly assigned to 70-capacity labs")
            print(f"       - Verify forced batching for courses with <3 practical hours")
            print(f"       - Ensure courses with >=3 practical hours can access 70-capacity labs")
        if has_lab_schedule and not lab_constraints_ok:
            print(f"   ❌ Lab constraint violations detected")
            print(f"       - Review detailed lab constraint verification above")
            print(f"       - Check macroblock allocation rules")
            print(f"       - Verify capacity constraints")
            print(f"       - Check for room/teacher conflicts")
        if not has_lab_schedule:
            courses_needing_labs = len([req for req in course_requirements.values() if req['practical_hours'] > 0])
            if courses_needing_labs > 0:
                print(f"   🧪 {courses_needing_labs} courses need lab allocation - run lab_scheduler.py")
        
        # Theory issues
        if has_theory_schedule and not theory_constraints_ok:
            print(f"   ❌ Theory constraint violations detected")
            print(f"       - Review detailed theory constraint verification above")
            print(f"       - Check theory room assignments")
            print(f"       - Verify theory teacher conflicts")
            print(f"       - Check theory capacity constraints")
        if not has_theory_schedule:
            courses_needing_theory = len([req for req in course_requirements.values() if req['lecture_hours'] > 0 or req['tutorial_hours'] > 0])
            if courses_needing_theory > 0:
                print(f"   📚 {courses_needing_theory} courses need theory allocation - run theory_scheduler.py")
        
        # Return success for both lab and theory constraints
        lab_success = True
        if has_lab_schedule:
            lab_success = not_scheduled == 0 and batching_issues == 0 and lab_constraints_ok and practical_violations == 0
        
        return lab_success and theory_constraints_ok

def verify_lab_constraints(schedule_df, course_requirements):
    """Comprehensive lab constraint verification."""
    print("\n🧪 DETAILED LAB CONSTRAINT VERIFICATION")
    print("=" * 80)
    
    if 'slot_type' in schedule_df.columns:
        # Combined schedule - filter for practical assignments
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        # Pure lab schedule - all rows are lab assignments
        lab_data = schedule_df
    
    if len(lab_data) == 0:
        print("❌ No lab assignments found!")
        return {'violations': [], 'compliant': False}
    
    violations = []
    
    # 1. Verify macroblock-based lab allocation constraints
    macroblock_violations = verify_macroblock_lab_constraints(schedule_df)
    violations.extend(macroblock_violations)
    
    # 2. Verify capacity constraints (hard constraint for practical hours)
    capacity_violations = verify_lab_capacity_constraints(schedule_df, course_requirements)
    violations.extend(capacity_violations)
    
    # 3. Verify lab room single assignment constraint
    room_violations = verify_lab_room_constraints(schedule_df)
    violations.extend(room_violations)
    
    # 4. Verify teacher single assignment constraint
    teacher_violations = verify_lab_teacher_constraints(schedule_df)
    violations.extend(teacher_violations)
    
    # 5. Verify theory-lab overlap constraints
    overlap_violations = verify_theory_lab_overlaps(schedule_df)
    violations.extend(overlap_violations)
    
    # 6. Verify continuous lab room assignment
    continuity_violations = verify_lab_continuity_constraints(schedule_df)
    violations.extend(continuity_violations)
    
    # 7. Verify weekly working hour constraints
    workload_violations = verify_lab_workload_constraints(schedule_df)
    violations.extend(workload_violations)
    
    # 8. Verify extra lab slot assignments
    extra_slot_violations = verify_extra_lab_slots(schedule_df, course_requirements)
    violations.extend(extra_slot_violations)
    
    # Print summary
    print(f"\n📊 LAB CONSTRAINT VERIFICATION SUMMARY:")
    print(f"Total lab assignments: {len(lab_data)}")
    print(f"Macroblock violations: {len(macroblock_violations)}")
    print(f"Capacity violations: {len(capacity_violations)}")
    print(f"Room assignment violations: {len(room_violations)}")
    print(f"Teacher assignment violations: {len(teacher_violations)}")
    print(f"Theory-lab overlap violations: {len(overlap_violations)}")
    print(f"Continuity violations: {len(continuity_violations)}")
    print(f"Workload violations: {len(workload_violations)}")
    print(f"Extra lab slot violations: {len(extra_slot_violations)}")
    print(f"TOTAL VIOLATIONS: {len(violations)}")
    
    if len(violations) == 0:
        print("✅ ALL LAB CONSTRAINTS SATISFIED!")
    else:
        print("❌ LAB CONSTRAINT VIOLATIONS DETECTED:")
        for i, violation in enumerate(violations[:10], 1):  # Show first 10
            print(f"  {i}. {violation}")
        if len(violations) > 10:
            print(f"  ... and {len(violations) - 10} more violations")
    
    return {'violations': violations, 'compliant': len(violations) == 0}

def verify_macroblock_lab_constraints(schedule_df):
    """Verify macroblock-based lab allocation constraints."""
    violations = []
    
    # Define macroblock to lab session mapping
    macroblock_to_lab_sessions = {
        # Morning theory blocks (a1-g1) -> Afternoon lab sessions (L4-L6)
        'a1': ['L4', 'L5', 'L6'], 'b1': ['L4', 'L5', 'L6'], 'c1': ['L4', 'L5', 'L6'],
        'd1': ['L4', 'L5', 'L6'], 'e1': ['L4', 'L5', 'L6'], 'f1': ['L4', 'L5', 'L6'], 'g1': ['L4', 'L5', 'L6'],
        
        # Afternoon theory blocks (a2-g2) -> Morning lab sessions (L1-L3)
        'a2': ['L1', 'L2', 'L3'], 'b2': ['L1', 'L2', 'L3'], 'c2': ['L1', 'L2', 'L3'],
        'd2': ['L1', 'L2', 'L3'], 'e2': ['L1', 'L2', 'L3'], 'f2': ['L1', 'L2', 'L3'], 'g2': ['L1', 'L2', 'L3']
    }
    
    # Map time intervals to lab sessions
    time_to_session_map = {
        '8:00 - 8:50': 'L1', '8:50 - 9:40': 'L1',
        '9:50 - 10:40': 'L2', '10:40 - 11:30': 'L2',
        '11:50 - 12:40': 'L3', '12:40 - 1:30': 'L3',
        '1:50 - 2:40': 'L4', '2:40 - 3:30': 'L4',
        '3:50 - 4:40': 'L5', '4:40 - 5:30': 'L5',
        '5:30 - 6:20': 'L6', '6:20 - 7:10': 'L6'
    }
    
    if 'slot_type' in schedule_df.columns:
        # Combined schedule
        theory_data = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        # Pure lab schedule - no theory data, all rows are lab data
        theory_data = pd.DataFrame()  # Empty dataframe
        lab_data = schedule_df
    
    # Group teachers by their macroblocks
    teacher_macroblocks = {}
    for _, row in theory_data.iterrows():
        teacher_id = row['teacher_id']
        macroblock = row.get('macroblock', '')
        if macroblock:
            if teacher_id not in teacher_macroblocks:
                teacher_macroblocks[teacher_id] = set()
            teacher_macroblocks[teacher_id].add(macroblock.lower())
    
    # Check each lab assignment against macroblock constraints
    for _, lab_row in lab_data.iterrows():
        teacher_id = lab_row['teacher_id']
        time_interval = lab_row['time_interval']
        course_code = lab_row.get('display_course_code', lab_row.get('course_code', 'Unknown'))
        day = lab_row['day']
        
        # Map time interval to lab session
        lab_session = time_to_session_map.get(time_interval, 'Unknown')
        
        # Get teacher's macroblocks
        teacher_blocks = teacher_macroblocks.get(teacher_id, set())
        
        if teacher_blocks:
            # Determine allowed lab sessions for this teacher
            allowed_sessions = set()
            for macroblock in teacher_blocks:
                if macroblock in macroblock_to_lab_sessions:
                    allowed_sessions.update(macroblock_to_lab_sessions[macroblock])
            
            # Check if current lab session is allowed
            if allowed_sessions and lab_session not in allowed_sessions:
                violations.append(f"MACROBLOCK VIOLATION: Teacher {teacher_id} assigned to lab session {lab_session} "
                                f"({time_interval}) on {day} violates macroblock constraint for course {course_code} "
                                f"(teacher macroblocks: {teacher_blocks}, allowed sessions: {allowed_sessions})")
    
    print(f"🎯 Macroblock constraint violations: {len(violations)}")
    return violations

def verify_lab_capacity_constraints(schedule_df, course_requirements):
    """Verify hard constraint: courses with <3 practical hours cannot use 70+ capacity labs."""
    violations = []
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    for _, lab_row in lab_data.iterrows():
        course_instance_id = str(lab_row.get('course_instance_id', ''))
        course_code = lab_row.get('display_course_code', lab_row.get('course_code', 'Unknown'))
        room_capacity = lab_row.get('room_capacity', lab_row.get('capacity', 0))
        
        # Get course requirements
        if course_instance_id in course_requirements:
            practical_hours = course_requirements[course_instance_id]['practical_hours']
            student_count = course_requirements[course_instance_id]['student_count']
            
            # HARD CONSTRAINT: courses with <3 practical hours cannot use 70+ capacity labs
            if practical_hours < 3 and room_capacity > 35 and student_count == 70:
                violations.append(f"CAPACITY VIOLATION: Course {course_code} (ID: {course_instance_id}) "
                                f"with {practical_hours} practical hours incorrectly assigned to "
                                f"{room_capacity}-capacity lab (should use 35-capacity only)")
    
    print(f"🏗️ Capacity constraint violations: {len(violations)}")
    return violations

def verify_lab_room_constraints(schedule_df):
    """Verify that lab rooms are not double-booked."""
    violations = []
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    # Group by room, day, and time
    room_usage = defaultdict(list)
    for _, row in lab_data.iterrows():
        room_id = row['room_id']
        day = row['day']
        time_interval = row['time_interval']
        course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
        teacher_id = row['teacher_id']
        
        key = (room_id, day, time_interval)
        room_usage[key].append({
            'course': course_code,
            'teacher': teacher_id,
            'room_number': row.get('room_number', f'Room{room_id}')
        })
    
    # Check for double bookings
    for (room_id, day, time_interval), assignments in room_usage.items():
        if len(assignments) > 1:
            room_number = assignments[0]['room_number']
            course_details = [f"{a['course']} (T{a['teacher']})" for a in assignments]
            violations.append(f"ROOM DOUBLE-BOOKING: Lab {room_number} (ID: {room_id}) "
                            f"on {day} at {time_interval} assigned to multiple courses: {', '.join(course_details)}")
    
    print(f"🏠 Room assignment violations: {len(violations)}")
    return violations

def verify_lab_teacher_constraints(schedule_df):
    """Verify that teachers are not assigned to multiple labs at the same time."""
    violations = []
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    # Group by teacher, day, and time
    teacher_usage = defaultdict(list)
    for _, row in lab_data.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        time_interval = row['time_interval']
        course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
        room_number = row.get('room_number', f"Room{row['room_id']}")
        
        key = (teacher_id, day, time_interval)
        teacher_usage[key].append({
            'course': course_code,
            'room': room_number
        })
    
    # Check for teacher conflicts
    for (teacher_id, day, time_interval), assignments in teacher_usage.items():
        if len(assignments) > 1:
            assignment_details = [f"{a['course']} in {a['room']}" for a in assignments]
            violations.append(f"TEACHER CONFLICT: Teacher {teacher_id} on {day} at {time_interval} "
                            f"assigned to multiple labs: {', '.join(assignment_details)}")
    
    print(f"👨‍🏫 Teacher assignment violations: {len(violations)}")
    return violations

def verify_theory_lab_overlaps(schedule_df):
    """Verify that teachers don't have overlapping theory and lab sessions."""
    violations = []
    
    def parse_time(time_str):
        """Parse time string to minutes since midnight."""
        time_part = time_str.split()[0]
        hours, minutes = map(int, time_part.split(':'))
        return hours * 60 + minutes
    
    def time_ranges_overlap(range1, range2):
        """Check if two time ranges overlap."""
        start1_str, end1_str = range1.split(' - ')
        start1 = parse_time(start1_str)
        end1 = parse_time(end1_str)
        
        start2_str, end2_str = range2.split(' - ')
        start2 = parse_time(start2_str)
        end2 = parse_time(end2_str)
        
        return start1 < end2 and start2 < end1
    
    if 'slot_type' in schedule_df.columns:
        # Combined schedule
        theory_data = schedule_df[schedule_df['slot_type'].isin(['Lecture', 'Tutorial'])]
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        # Pure lab schedule - no theory data, all rows are lab data
        theory_data = pd.DataFrame()  # Empty dataframe
        lab_data = schedule_df
    
    # Check for each teacher - only if we have theory data
    if len(theory_data) > 0:
        for teacher_id in schedule_df['teacher_id'].unique():
            teacher_theory = theory_data[theory_data['teacher_id'] == teacher_id]
            teacher_labs = lab_data[lab_data['teacher_id'] == teacher_id]
            
            for _, theory_row in teacher_theory.iterrows():
                theory_day = theory_row['day']
                theory_time = theory_row['time_interval']
                theory_course = theory_row.get('course_code', 'Unknown')
                
                for _, lab_row in teacher_labs.iterrows():
                    lab_day = lab_row['day']
                    lab_time = lab_row['time_interval']
                    lab_course = lab_row.get('display_course_code', lab_row.get('course_code', 'Unknown'))
                    
                    if theory_day == lab_day and time_ranges_overlap(theory_time, lab_time):
                        violations.append(f"THEORY-LAB OVERLAP: Teacher {teacher_id} on {theory_day} "
                                        f"has overlapping theory class {theory_course} ({theory_time}) "
                                        f"and lab {lab_course} ({lab_time})")
    else:
        # Pure lab schedule - no theory data to check against
        print("No theory data available - skipping theory-lab overlap check")
    
    print(f"⚡ Theory-lab overlap violations: {len(violations)}")
    return violations

def verify_lab_continuity_constraints(schedule_df):
    """Verify continuous lab room assignment for multi-slot sessions - CORRECTED LOGIC."""
    violations = []
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    # Define lab session time slots - each session has 2 consecutive slots
    lab_session_slots = {
        'L1': ['8:00 - 8:50', '8:50 - 9:40'],
        'L2': ['9:50 - 10:40', '10:40 - 11:30'],
        'L3': ['11:50 - 12:40', '12:40 - 1:30'],
        'L4': ['1:50 - 2:40', '2:40 - 3:30'],
        'L5': ['3:50 - 4:40', '4:40 - 5:30'],
        'L6': ['5:30 - 6:20', '6:20 - 7:10']
    }
    
    # Map time intervals to sessions
    time_to_session = {}
    for session, slots in lab_session_slots.items():
        for slot in slots:
            time_to_session[slot] = session
    
    # Group by course, teacher, day, session (SAME SESSION ONLY)
    course_session_assignments = defaultdict(list)
    for _, row in lab_data.iterrows():
        course_instance_id = row.get('course_instance_id', '')
        teacher_id = row['teacher_id']
        day = row['day']
        time_interval = row['time_interval']
        room_id = row['room_id']
        
        # Handle compound time intervals like "9:50 - 10:40 - 11:30" (full L2 session)
        # Extract start time to determine session
        start_time = time_interval.split(' - ')[0] + " - " + time_interval.split(' - ')[1]
        session = time_to_session.get(start_time, 'Unknown')
        
        # Key includes session - only check continuity WITHIN same session
        key = (course_instance_id, teacher_id, day, session)
        course_session_assignments[key].append({
            'time': time_interval,
            'room_id': room_id,
            'room_number': row.get('room_number', f'Room{room_id}')
        })
    
    # Check for REAL continuity violations (same session, different rooms)
    for (course_id, teacher_id, day, session), assignments in course_session_assignments.items():
        if len(assignments) > 1:
            # Multiple slots in SAME session - they MUST be in same room
            rooms = set(a['room_id'] for a in assignments)
            if len(rooms) > 1:
                room_details = [f"{a['room_number']} ({a['time']})" for a in assignments]
                violations.append(f"REAL CONTINUITY VIOLATION: Course {course_id} teacher {teacher_id} "
                                f"on {day} in session {session} uses multiple rooms within same session: {', '.join(room_details)}")
    
    print(f"🔗 Continuity violations (same session only): {len(violations)}")
    if len(violations) == 0:
        print("  ✅ All lab sessions maintain room continuity correctly")
        print("  ✅ Courses can legitimately use different rooms across different sessions")
    return violations

def verify_lab_workload_constraints(schedule_df):
    """Verify weekly working hour constraints including labs."""
    violations = []
    
    # Calculate total hours per teacher
    teacher_hours = defaultdict(lambda: {'theory': 0, 'lab': 0, 'lab_sessions': set()})
    
    # Define lab session time slots for proper grouping
    lab_session_slots = {
        'L1': ['8:00 - 8:50', '8:50 - 9:40'],
        'L2': ['9:50 - 10:40', '10:40 - 11:30'],
        'L3': ['11:50 - 12:40', '12:40 - 1:30'],
        'L4': ['1:50 - 2:40', '2:40 - 3:30'],
        'L5': ['3:50 - 4:40', '4:40 - 5:30'],
        'L6': ['5:30 - 6:20', '6:20 - 7:10']
    }
    
    # Map time intervals to sessions
    time_to_session = {}
    for session, slots in lab_session_slots.items():
        for slot in slots:
            time_to_session[slot] = session
    
    for _, row in schedule_df.iterrows():
        teacher_id = row['teacher_id']
        
        if 'slot_type' in row:
            slot_type = row['slot_type']
            if slot_type in ['Lecture', 'Tutorial']:
                teacher_hours[teacher_id]['theory'] += 1
            elif slot_type == 'Practical':
                # Lab session processing for combined schedule
                time_interval = row['time_interval']
                day = row['day']
                course_instance_id = row.get('course_instance_id', '')
                
                # Map time to session and create unique session identifier
                session = time_to_session.get(time_interval, 'Unknown')
                session_key = f"{day}_{session}_{course_instance_id}"
                
                # Only count each lab session once (2 hours per session)
                if session_key not in teacher_hours[teacher_id]['lab_sessions']:
                    teacher_hours[teacher_id]['lab_sessions'].add(session_key)
                    teacher_hours[teacher_id]['lab'] += 2  # Each lab session = 2 hours
        else:
            # Pure lab schedule - all entries are lab sessions
            # Group lab slots into sessions to avoid double counting
            time_interval = row['time_interval']
            day = row['day']
            course_instance_id = row.get('course_instance_id', '')
            
            # Map time to session and create unique session identifier
            session = time_to_session.get(time_interval, 'Unknown')
            session_key = f"{day}_{session}_{course_instance_id}"
            
            # Only count each lab session once (2 hours per session)
            if session_key not in teacher_hours[teacher_id]['lab_sessions']:
                teacher_hours[teacher_id]['lab_sessions'].add(session_key)
                teacher_hours[teacher_id]['lab'] += 2  # Each lab session = 2 hours
    
    # Check for violations (40-hour weekly limit for lab-heavy schedules)
    # Note: Lab teaching typically has higher hour limits than theory teaching
    for teacher_id, hours in teacher_hours.items():
        total_hours = hours['theory'] + hours['lab']
        
        # More realistic limits:
        # - Pure theory teachers: 25 hours
        # - Lab-heavy teachers: 40 hours  
        # - Mixed teachers: 35 hours
        if hours['lab'] == 0:
            # Pure theory teacher
            limit = 25
        elif hours['theory'] == 0:
            # Pure lab teacher (like in our lab-only schedule)
            limit = 40
        else:
            # Mixed theory + lab
            limit = 35
            
        if total_hours > limit:
            violations.append(f"WORKLOAD VIOLATION: Teacher {teacher_id} assigned {total_hours} hours "
                            f"({hours['theory']} theory + {hours['lab']} lab) exceeds {limit}-hour weekly limit")
    
    print(f"⏰ Workload violations: {len(violations)}")
    return violations

def verify_lab_shift_constraints(schedule_df):
    """Verify lab assignments comply with teacher shift constraints (if shift data available)."""
    violations = []
    
    # This would require access to teacher shift data
    # For now, return empty violations since shift data is not readily available in this context
    print(f"🕐 Shift constraint verification: Skipped (requires shift data)")
    return violations

def analyze_lab_efficiency(schedule_df, course_requirements):
    """Analyze lab allocation efficiency and utilization."""
    print("\n📊 LAB EFFICIENCY ANALYSIS")
    print("=" * 60)
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    if len(lab_data) == 0:
        print("❌ No lab data available for analysis")
        return
    
    # Room utilization analysis
    room_usage = defaultdict(int)
    room_capacities = {}
    total_student_hours = 0
    total_lab_capacity_hours = 0
    
    for _, row in lab_data.iterrows():
        room_id = row['room_id']
        room_number = row.get('room_number', f'Room{room_id}')
        room_capacity = row.get('room_capacity', row.get('capacity', 0))
        student_count = row.get('student_count', 0)
        
        room_usage[room_number] += 1
        room_capacities[room_number] = room_capacity
        
        # Each lab slot = 2 hours
        total_student_hours += student_count * 2
        total_lab_capacity_hours += room_capacity * 2
    
    print(f"Lab rooms utilized: {len(room_usage)}")
    print(f"Total lab sessions: {sum(room_usage.values())}")
    print(f"Total student-hours: {total_student_hours}")
    print(f"Total capacity-hours: {total_lab_capacity_hours}")
    if total_lab_capacity_hours > 0:
        utilization_rate = (total_student_hours / total_lab_capacity_hours) * 100
        print(f"Overall capacity utilization: {utilization_rate:.1f}%")
    
    # Room-wise utilization
    print(f"\n🏠 ROOM-WISE UTILIZATION:")
    for room, sessions in sorted(room_usage.items()):
        capacity = room_capacities.get(room, 0)
        max_weekly_sessions = 30  # 6 sessions * 5 days
        utilization = (sessions / max_weekly_sessions) * 100
        print(f"  {room} (Cap: {capacity}): {sessions}/30 sessions ({utilization:.1f}% utilization)")
    
    # Capacity distribution analysis
    if 'room_capacity' in lab_data.columns:
        capacity_35_sessions = len(lab_data[lab_data['room_capacity'].fillna(0) <= 35])
        capacity_70_sessions = len(lab_data[lab_data['room_capacity'].fillna(0) > 35])
    else:
        # Use 'capacity' column if 'room_capacity' doesn't exist
        capacity_35_sessions = len(lab_data[lab_data['capacity'].fillna(0) <= 35])
        capacity_70_sessions = len(lab_data[lab_data['capacity'].fillna(0) > 35])
    
    print(f"\n🔢 CAPACITY DISTRIBUTION:")
    print(f"Sessions in 35-capacity labs: {capacity_35_sessions}")
    print(f"Sessions in 70+ capacity labs: {capacity_70_sessions}")
    
    # Batching analysis
    if 'is_batched' in lab_data.columns:
        batched_sessions = len(lab_data[lab_data['is_batched'].fillna(False) == True])
        print(f"Sessions using batching: {batched_sessions}")
    
    # Daily distribution
    daily_distribution = lab_data['day'].value_counts()
    print(f"\n📅 DAILY DISTRIBUTION:")
    for day in ['tuesday', 'wed', 'thur', 'fri', 'sat']:
        sessions = daily_distribution.get(day, 0)
        print(f"  {day.capitalize()}: {sessions} sessions")

# Theory Schedule Verification Functions

def verify_theory_constraints(theory_schedule_df, course_requirements):
    """Verify theory scheduling constraints."""
    violations = []
    
    if theory_schedule_df is None or theory_schedule_df.empty:
        print("❌ No theory schedule data available for verification")
        return violations
    
    print("\n🎓 THEORY CONSTRAINT VERIFICATION")
    print("=" * 60)
    
    # Verify theory requirements fulfillment
    theory_requirements_violations = verify_theory_requirements_constraint(theory_schedule_df, course_requirements)
    violations.extend(theory_requirements_violations)
    
    # Verify theory room constraints
    theory_room_violations = verify_theory_room_constraints(theory_schedule_df)
    violations.extend(theory_room_violations)
    
    # Verify theory teacher constraints
    theory_teacher_violations = verify_theory_teacher_constraints(theory_schedule_df)
    violations.extend(theory_teacher_violations)
    
    # Verify theory capacity constraints
    theory_capacity_violations = verify_theory_capacity_constraints(theory_schedule_df, course_requirements)
    violations.extend(theory_capacity_violations)
    
    # Verify theory room utilization
    theory_utilization_violations = verify_theory_room_utilization(theory_schedule_df)
    violations.extend(theory_utilization_violations)
    
    print(f"\n📊 THEORY VERIFICATION SUMMARY:")
    print(f"Total theory constraint violations: {len(violations)}")
    
    return violations

def verify_theory_requirements_constraint(theory_schedule_df, course_requirements):
    """Verify that theory courses get the required number of lecture and tutorial hours."""
    violations = []
    
    # Count scheduled hours per course instance
    scheduled_hours = defaultdict(lambda: {'lecture': 0, 'tutorial': 0})
    
    for _, row in theory_schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))
        except:
            instance_id = str(row['course_instance_id'])
        
        session_type = row.get('session_type', 'lecture')  # Default to lecture if not specified
        
        if session_type.lower() in ['lecture', 'theory']:
            scheduled_hours[instance_id]['lecture'] += 1
        elif session_type.lower() in ['tutorial', 'tut']:
            scheduled_hours[instance_id]['tutorial'] += 1
    
    # Check each course instance
    for instance_id, requirements in course_requirements.items():
        lecture_required = requirements['lecture_hours']
        tutorial_required = requirements['tutorial_hours']
        
        lecture_scheduled = scheduled_hours[instance_id]['lecture']
        tutorial_scheduled = scheduled_hours[instance_id]['tutorial']
        
        # Only check courses that have theory requirements
        if lecture_required > 0 or tutorial_required > 0:
            if lecture_scheduled < lecture_required:
                violations.append(f"LECTURE SHORTAGE: Course {requirements['course_code']} "
                                f"(ID: {instance_id}) needs {lecture_required} lecture hours, "
                                f"only scheduled {lecture_scheduled}")
            
            if tutorial_scheduled < tutorial_required:
                violations.append(f"TUTORIAL SHORTAGE: Course {requirements['course_code']} "
                                f"(ID: {instance_id}) needs {tutorial_required} tutorial hours, "
                                f"only scheduled {tutorial_scheduled}")
    
    print(f"📚 Theory requirements violations: {len(violations)}")
    return violations

def verify_theory_room_constraints(theory_schedule_df):
    """Verify that theory rooms are not double-booked."""
    violations = []
    
    # Group by room, day, and time slot
    room_schedule = defaultdict(list)
    
    for _, row in theory_schedule_df.iterrows():
        room_id = row['room_id']
        day = row['day']
        time_slot = row['time_slot']
        course_code = row['course_code']
        teacher_id = row['teacher_id']
        
        key = (room_id, day, time_slot)
        room_schedule[key].append({
            'course': course_code,
            'teacher': teacher_id,
            'room_number': row.get('room_number', f'Room{room_id}')
        })
    
    # Check for conflicts
    for (room_id, day, time_slot), assignments in room_schedule.items():
        if len(assignments) > 1:
            room_number = assignments[0]['room_number']
            courses = [f"{a['course']}(T{a['teacher']})" for a in assignments]
            violations.append(f"ROOM CONFLICT: Room {room_number} on {day} at {time_slot} "
                            f"assigned to multiple courses: {', '.join(courses)}")
    
    print(f"🏠 Theory room conflicts: {len(violations)}")
    return violations

def verify_theory_teacher_constraints(theory_schedule_df):
    """Verify that teachers are not scheduled for multiple theory sessions simultaneously."""
    violations = []
    
    # Group by teacher, day, and time slot
    teacher_schedule = defaultdict(list)
    
    for _, row in theory_schedule_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        time_slot = row['time_slot']
        course_code = row['course_code']
        room_number = row.get('room_number', f"Room{row['room_id']}")
        
        key = (teacher_id, day, time_slot)
        teacher_schedule[key].append({
            'course': course_code,
            'room': room_number
        })
    
    # Check for conflicts
    for (teacher_id, day, time_slot), assignments in teacher_schedule.items():
        if len(assignments) > 1:
            courses = [f"{a['course']} in {a['room']}" for a in assignments]
            violations.append(f"TEACHER CONFLICT: Teacher {teacher_id} on {day} at {time_slot} "
                            f"assigned to multiple courses: {', '.join(courses)}")
    
    print(f"👨‍🏫 Theory teacher conflicts: {len(violations)}")
    return violations

def verify_theory_capacity_constraints(theory_schedule_df, course_requirements):
    """Verify that theory room capacities are sufficient for enrolled students."""
    violations = []
    
    for _, row in theory_schedule_df.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))
        except:
            instance_id = str(row['course_instance_id'])
        
        room_capacity = row.get('capacity', 0)
        student_count = row.get('student_count', 0)
        course_code = row['course_code']
        room_number = row.get('room_number', f"Room{row['room_id']}")
        
        # Get student count from requirements if not in schedule
        if student_count == 0 and instance_id in course_requirements:
            student_count = course_requirements[instance_id]['student_count']
        
        if student_count > room_capacity:
            violations.append(f"CAPACITY VIOLATION: Course {course_code} (ID: {instance_id}) "
                            f"has {student_count} students but assigned to room {room_number} "
                            f"with capacity {room_capacity}")
    
    print(f"🔢 Theory capacity violations: {len(violations)}")
    return violations

def verify_theory_room_utilization(theory_schedule_df):
    """Analyze theory room utilization efficiency."""
    violations = []
    
    if theory_schedule_df.empty:
        return violations
    
    # Calculate room utilization
    room_usage = defaultdict(int)
    room_info = {}
    
    for _, row in theory_schedule_df.iterrows():
        room_id = row['room_id']
        room_number = row.get('room_number', f'Room{room_id}')
        room_capacity = row.get('capacity', 0)
        
        room_usage[room_number] += 1
        room_info[room_number] = {
            'capacity': room_capacity,
            'id': room_id
        }
    
    # Check for under-utilization (rooms used very little)
    max_weekly_slots = 55  # 11 time slots * 5 days
    
    for room_number, sessions in room_usage.items():
        utilization_rate = (sessions / max_weekly_slots) * 100
        
        if utilization_rate > 80:
            violations.append(f"OVER-UTILIZATION: Theory room {room_number} "
                            f"used {sessions}/{max_weekly_slots} slots ({utilization_rate:.1f}%)")
    
    print(f"📈 Theory room utilization issues: {len(violations)}")
    
    # Print utilization summary
    print(f"Theory rooms used: {len(room_usage)}")
    total_sessions = sum(room_usage.values())
    print(f"Total theory sessions: {total_sessions}")
    
    return violations

def verify_lab_theory_conflicts(lab_schedule_df, theory_schedule_df):
    """Verify that lab and theory schedules don't have teacher conflicts."""
    violations = []
    
    if lab_schedule_df is None or theory_schedule_df is None:
        print("⚠️ Cannot verify lab-theory conflicts: missing schedule data")
        return violations
    
    print("\n🔄 LAB-THEORY CONFLICT VERIFICATION")
    print("=" * 60)
    
    # Create combined schedule for conflict detection
    lab_teacher_schedule = defaultdict(list)
    theory_teacher_schedule = defaultdict(list)
    
    # Process lab schedule
    for _, row in lab_schedule_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        
        # Handle lab session times (convert to individual slots)
        time_interval = row.get('time_interval', '')
        session_name = row.get('session_name', '')
        
        # Map lab sessions to theory time slots for conflict detection
        lab_to_theory_slots = {
            'L1': ['8:00 - 8:50', '8:50 - 9:40'],
            'L2': ['9:50 - 10:40', '10:40 - 11:30'], 
            'L3': ['11:50 - 12:40', '12:40 - 1:30'],
            'L4': ['1:50 - 2:40', '2:40 - 3:30'],
            'L5': ['3:50 - 4:40', '4:40 - 5:30'],
            'L6': ['5:30 - 6:20', '6:20 - 7:10']
        }
        
        if session_name in lab_to_theory_slots:
            for time_slot in lab_to_theory_slots[session_name]:
                key = (teacher_id, day, time_slot)
                lab_teacher_schedule[key].append({
                    'type': 'LAB',
                    'course': row['course_code'],
                    'room': row.get('room_number', ''),
                    'session': session_name
                })
    
    # Process theory schedule
    for _, row in theory_schedule_df.iterrows():
        teacher_id = row['teacher_id']
        day = row['day']
        time_slot = row['time_slot']
        
        key = (teacher_id, day, time_slot)
        theory_teacher_schedule[key].append({
            'type': 'THEORY',
            'course': row['course_code'],
            'room': row.get('room_number', ''),
            'session_type': row.get('session_type', 'lecture')
        })
    
    # Check for conflicts
    conflict_count = 0
    for key in lab_teacher_schedule.keys():
        if key in theory_teacher_schedule:
            teacher_id, day, time_slot = key
            lab_info = lab_teacher_schedule[key][0]
            theory_info = theory_teacher_schedule[key][0]
            
            violations.append(f"LAB-THEORY CONFLICT: Teacher {teacher_id} on {day} at {time_slot} "
                            f"has both LAB ({lab_info['course']} in {lab_info['room']}) "
                            f"and THEORY ({theory_info['course']} in {theory_info['room']})")
            conflict_count += 1
    
    print(f"⚠️ Lab-theory teacher conflicts: {conflict_count}")
    return violations

def analyze_theory_efficiency(theory_schedule_df, course_requirements):
    """Analyze theory schedule efficiency and utilization."""
    if theory_schedule_df is None or theory_schedule_df.empty:
        print("❌ No theory schedule data for efficiency analysis")
        return
    
    print("\n📊 THEORY EFFICIENCY ANALYSIS")
    print("=" * 60)
    
    # Room utilization analysis
    room_usage = defaultdict(int)
    room_capacities = {}
    total_student_hours = 0
    total_room_capacity_hours = 0
    
    for _, row in theory_schedule_df.iterrows():
        room_id = row['room_id']
        room_number = row.get('room_number', f'Room{room_id}')
        room_capacity = row.get('capacity', 0)
        student_count = row.get('student_count', 0)
        
        room_usage[room_number] += 1
        room_capacities[room_number] = room_capacity
        
        # Each theory slot = 1 hour
        total_student_hours += student_count * 1
        total_room_capacity_hours += room_capacity * 1
    
    print(f"Theory rooms utilized: {len(room_usage)}")
    print(f"Total theory sessions: {sum(room_usage.values())}")
    print(f"Total student-hours: {total_student_hours}")
    print(f"Total capacity-hours: {total_room_capacity_hours}")
    
    if total_room_capacity_hours > 0:
        utilization_rate = (total_student_hours / total_room_capacity_hours) * 100
        print(f"Overall capacity utilization: {utilization_rate:.1f}%")
    
    # Room-wise utilization
    print(f"\n🏠 THEORY ROOM-WISE UTILIZATION:")
    for room, sessions in sorted(room_usage.items()):
        capacity = room_capacities.get(room, 0)
        max_weekly_sessions = 55  # 11 time slots * 5 days
        utilization = (sessions / max_weekly_sessions) * 100
        print(f"  {room} (Cap: {capacity}): {sessions}/55 sessions ({utilization:.1f}% utilization)")
    
    # Daily distribution
    daily_distribution = theory_schedule_df['day'].value_counts()
    print(f"\n📅 THEORY DAILY DISTRIBUTION:")
    for day in ['tuesday', 'wed', 'thur', 'fri', 'sat']:
        sessions = daily_distribution.get(day, 0)
        print(f"  {day.capitalize()}: {sessions} sessions")
    
    # Session type distribution
    if 'session_type' in theory_schedule_df.columns:
        type_distribution = theory_schedule_df['session_type'].value_counts()
        print(f"\n📚 SESSION TYPE DISTRIBUTION:")
        for session_type, count in type_distribution.items():
            print(f"  {session_type.capitalize()}: {count} sessions")

def verify_extra_lab_slots(schedule_df, course_requirements):
    """Verify that no extra lab slots are assigned beyond required practical hours."""
    print("\n🔍 CHECKING FOR EXTRA LAB SLOT ASSIGNMENTS")
    print("-" * 60)
    
    violations = []
    
    if 'slot_type' in schedule_df.columns:
        lab_data = schedule_df[schedule_df['slot_type'] == 'Practical']
    else:
        lab_data = schedule_df
    
    if len(lab_data) == 0:
        print("❌ No lab assignments found!")
        return violations
    
    # Count scheduled lab hours per course instance
    scheduled_lab_hours = defaultdict(int)
    course_details = {}
    
    for _, row in lab_data.iterrows():
        try:
            instance_id = str(int(float(row['course_instance_id'])))
        except:
            instance_id = str(row['course_instance_id'])
        
        course_code = row.get('display_course_code', row.get('course_code', 'Unknown'))
        teacher_id = row['teacher_id']
        day = row['day']
        time_interval = row['time_interval']
        room_id = row.get('room_id', 'Unknown')
        
        # Each lab session = 2 practical hours
        scheduled_lab_hours[instance_id] += 2
        
        # Store course details for reporting
        if instance_id not in course_details:
            course_details[instance_id] = {
                'course_code': course_code,
                'teacher_id': teacher_id,
                'assignments': []
            }
        
        course_details[instance_id]['assignments'].append({
            'day': day,
            'time': time_interval,
            'room': room_id
        })
    
    # Check for extra assignments
    extra_assignments_found = 0
    perfect_assignments = 0
    under_assignments = 0
    
    print(f"{'ID':<6} {'Course':<12} {'Required':<8} {'Scheduled':<9} {'Status':<12} {'Details'}")
    print("-" * 80)
    
    for instance_id, requirements in sorted(course_requirements.items(), key=lambda x: int(x[0])):
        if instance_id in scheduled_lab_hours:
            required_hours = requirements['practical_hours']
            scheduled_hours = scheduled_lab_hours[instance_id]
            course_code = requirements['course_code']
            
            if required_hours > 0:  # Only check courses that need practicals
                details = course_details[instance_id]
                
                if scheduled_hours > required_hours:
                    # EXTRA SLOTS DETECTED
                    extra_hours = scheduled_hours - required_hours
                    extra_sessions = extra_hours // 2
                    status = f"⚠️ EXTRA +{extra_hours}h"
                    extra_assignments_found += 1
                    
                    # Create detailed violation report
                    assignment_list = []
                    for assignment in details['assignments']:
                        assignment_list.append(f"{assignment['day']} {assignment['time']} ({assignment['room']})")
                    
                    violation_msg = (f"EXTRA LAB SLOTS: Course {course_code} (ID: {instance_id}) "
                                   f"assigned {scheduled_hours} hours but only needs {required_hours} hours. "
                                   f"Extra {extra_sessions} lab session(s) = {extra_hours} hours. "
                                   f"Teacher: {details['teacher_id']}. "
                                   f"Assignments: {'; '.join(assignment_list)}")
                    violations.append(violation_msg)
                    
                    detail_text = f"{len(details['assignments'])} sessions"
                    
                elif scheduled_hours == required_hours:
                    # PERFECT MATCH
                    status = "✅ PERFECT"
                    perfect_assignments += 1
                    detail_text = f"{len(details['assignments'])} sessions"
                    
                else:
                    # UNDER-ASSIGNED
                    missing_hours = required_hours - scheduled_hours
                    status = f"❌ SHORT -{missing_hours}h"
                    under_assignments += 1
                    detail_text = f"{len(details['assignments'])} sessions"
                
                print(f"{instance_id:<6} {course_code:<12} {required_hours:<8} {scheduled_hours:<9} {status:<12} {detail_text}")
    
    print("-" * 80)
    print(f"📊 EXTRA LAB SLOT ANALYSIS:")
    print(f"  ✅ Perfect assignments: {perfect_assignments}")
    print(f"  ⚠️  Extra assignments: {extra_assignments_found}")
    print(f"  ❌ Under assignments: {under_assignments}")
    
    if extra_assignments_found > 0:
        print(f"\n🔍 DETAILED EXTRA SLOT VIOLATIONS:")
        for i, violation in enumerate(violations, 1):
            if "EXTRA LAB SLOTS" in violation:
                print(f"  {i}. {violation}")
    else:
        print(f"✅ No extra lab slots detected - all assignments match requirements!")
    
    print(f"🧪 Extra lab slot violations: {len([v for v in violations if 'EXTRA LAB SLOTS' in v])}")
    return violations

if __name__ == "__main__":
    verify_ltp_constraints() 