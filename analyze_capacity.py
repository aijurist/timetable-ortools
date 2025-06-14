#!/usr/bin/env python3

import json
import os
from collections import defaultdict

def analyze_scheduling_capacity():
    # Find latest lab schedule
    lab_dirs = [d for d in os.listdir('output') if d.startswith('lab_schedule_')]
    if not lab_dirs:
        print("No lab schedule found")
        return
    
    latest_lab_dir = sorted(lab_dirs)[-1]
    lab_file = os.path.join('output', latest_lab_dir, 'lab_schedule.json')
    
    with open(lab_file, 'r') as f:
        lab_data = json.load(f)
    
    print(f"=== LAB SCHEDULE ANALYSIS ===")
    print(f"Lab sessions: {len(lab_data)}")
    
    # Count unique lab groups
    lab_groups = set()
    for session in lab_data:
        dept = session.get('department', '')
        semester = session.get('semester', 0)
        group_idx = session.get('group_index', 0)
        lab_groups.add(f'{dept}_S{semester}_G{group_idx}')
    
    print(f"Unique lab groups: {len(lab_groups)}")
    
    # Count lab timeslots that would conflict with theory
    theory_time_slots = [
        "8:00 - 8:50", "9:00 - 9:50", "10:00 - 10:50", "11:00 - 11:50",
        "12:00 - 12:50", "1:00 - 1:50", "2:00 - 2:50", "3:00 - 3:50", 
        "4:00 - 4:50", "5:00 - 5:50", "6:00 - 6:50"
    ]
    
    days = ["tuesday", "wed", "thur", "fri", "sat"]
    
    # Map lab intervals to theory slots
    def map_lab_interval_to_theory_slots(lab_time_interval):
        def time_to_minutes_for_lab_interval(time_str, is_end_time=False):
            try:
                hour, minute = map(int, time_str.split(':'))
                if is_end_time and hour >= 1 and hour <= 7 and hour != 11 and hour != 12:
                    hour += 12
                return hour * 60 + minute
            except ValueError:
                return 0
        
        def time_ranges_overlap(start1, end1, start2, end2):
            return start1 < end2 and start2 < end1
        
        try:
            time_parts = lab_time_interval.split(' - ')
            if len(time_parts) != 3:
                return []
            
            lab_start_str, lab_middle_str, lab_end_str = time_parts
            lab_start_min = time_to_minutes_for_lab_interval(lab_start_str, is_end_time=False)
            lab_end_min = time_to_minutes_for_lab_interval(lab_end_str, is_end_time=True)
            
        except Exception:
            return []
        
        overlapping_slots = []
        for theory_slot in theory_time_slots:
            try:
                theory_start_str, theory_end_str = theory_slot.split(' - ')
                theory_start_min = time_to_minutes_for_lab_interval(theory_start_str, is_end_time=False)
                theory_end_min = time_to_minutes_for_lab_interval(theory_end_str, is_end_time=False)
                
                if time_ranges_overlap(lab_start_min, lab_end_min, theory_start_min, theory_end_min):
                    overlapping_slots.append(theory_slot)
                    
            except Exception:
                continue
        
        return overlapping_slots
    
    # Count blocked theory timeslots
    blocked_theory_timeslots = set()
    lab_timeslot_conflicts = defaultdict(list)
    
    for session in lab_data:
        day = session.get('day', '')
        time_interval = session.get('time_interval', '')
        dept = session.get('department', '')
        semester = session.get('semester', 0)
        
        if day and time_interval:
            overlapping_theory_slots = map_lab_interval_to_theory_slots(time_interval)
            for theory_slot in overlapping_theory_slots:
                day_timeslot = f"{day}_{theory_slot}"
                blocked_theory_timeslots.add(day_timeslot)
                lab_timeslot_conflicts[day_timeslot].append(f"{dept}_S{semester}")
    
    print(f"Blocked theory timeslots: {len(blocked_theory_timeslots)}")
    
    # Calculate total theory capacity
    total_theory_timeslots = len(days) * len(theory_time_slots)  # 5 days * 11 slots = 55
    available_theory_timeslots = total_theory_timeslots - len(blocked_theory_timeslots)
    
    print(f"Total theory timeslots per week: {total_theory_timeslots}")
    print(f"Available theory timeslots after lab conflicts: {available_theory_timeslots}")
    print(f"Blocked percentage: {len(blocked_theory_timeslots) / total_theory_timeslots * 100:.1f}%")
    
    # Show most conflicted timeslots
    print(f"\nMost conflicted theory timeslots:")
    conflict_counts = [(len(conflicts), timeslot) for timeslot, conflicts in lab_timeslot_conflicts.items()]
    for count, timeslot in sorted(conflict_counts, reverse=True)[:10]:
        print(f"  {timeslot}: {count} lab conflicts")
    
    # Estimate theory group requirements
    print(f"\n=== THEORY GROUP ANALYSIS ===")
    
    # Count theory groups from the log output (approximate)
    # Based on the log, we can see groups like "Computer Science & Engineering_S3_G1" etc.
    theory_groups_estimate = 0
    
    # From the log, we can count the theory groups mentioned
    dept_semester_groups = {
        ("Computer Science & Engineering (Cyber Security)", 3): 3,
        ("Computer Science & Engineering (Cyber Security)", 5): 5,
        ("Artificial Intelligence & Data Science", 3): 2,
        ("Artificial Intelligence & Data Science", 5): 5,
        ("Artificial Intelligence & Data Science", 7): 2,
        ("Computer Science & Design", 3): 6,
        ("Computer Science & Design", 5): 5,
        ("Computer Science & Design", 7): 6,
        ("Artificial Intelligence & Machine Learning", 3): 6,
        ("Artificial Intelligence & Machine Learning", 5): 7,
        ("Artificial Intelligence & Machine Learning", 7): 7,
        ("Computer Science & Business Systems", 3): 7,
        ("Computer Science & Business Systems", 5): 4,
        ("Computer Science & Business Systems", 7): 4,
        ("Computer Science & Engineering", 3): 6,
        ("Computer Science & Engineering", 5): 5,
        ("Computer Science & Engineering", 6): 1,
        ("Computer Science & Engineering", 7): 5,
        ("Information Technology", 3): 6,
        ("Information Technology", 5): 5,
        ("Information Technology", 7): 5,
    }
    
    total_theory_groups = sum(dept_semester_groups.values())
    print(f"Estimated theory groups: {total_theory_groups}")
    
    # Assume each group needs 3-6 time slots
    min_slots_needed = total_theory_groups * 3
    max_slots_needed = total_theory_groups * 6
    
    print(f"Theory slots needed (3 per group): {min_slots_needed}")
    print(f"Theory slots needed (6 per group): {max_slots_needed}")
    print(f"Available theory slots: {available_theory_timeslots}")
    
    if min_slots_needed > available_theory_timeslots:
        print(f"❌ INFEASIBLE: Need at least {min_slots_needed} slots but only {available_theory_timeslots} available")
        shortage = min_slots_needed - available_theory_timeslots
        print(f"   Shortage: {shortage} slots")
        print(f"   Need to reduce theory groups by: {shortage // 3} groups")
    elif max_slots_needed > available_theory_timeslots:
        print(f"⚠️ TIGHT: Max need {max_slots_needed} slots, available {available_theory_timeslots}")
        print(f"   May need to reduce slot requirements per group")
    else:
        print(f"✅ FEASIBLE: Enough slots available")

if __name__ == "__main__":
    analyze_scheduling_capacity() 