"""02 — Time configurations

Defines lab and theory time slots and demonstrates mapping between lab sessions
(2-hour blocks) and theory 1-hour slots. This mirrors the time configuration in
`combined_scheduler.py` but with a small, clear example.
"""

def build_time_config():
    theory_slots = [
        "8:00 - 8:50", "8:55 - 9:45", "9:50 - 10:40",
        "10:45 - 11:35", "11:40 - 12:30", "12:35 - 1:20",
        "1:50 - 2:40", "3:20 - 4:10", "4:15 - 5:05"
    ]
    
    #................................
    
    lab_slots = [
        "8:00 - 8:50", "8:50 - 9:40", "9:50 - 10:40", "10:40 - 11:30",
        "11:40 - 12:30", "12:30 - 1:20"
    ]

    # Group lab slots into 2-hour sessions
    lab_sessions = {
        'L1': {'slots': [0, 1], 'time_range': '8:00 - 9:40'},
        'L2': {'slots': [2, 3], 'time_range': '9:50 - 11:30'},
        'L3': {'slots': [4, 5], 'time_range': '11:40 - 1:20'}
    }

    # Build mapping: theory slot index -> lab session name (if overlapping)
    mapping = {}
    for t_idx, t in enumerate(theory_slots):
        for name, info in lab_sessions.items():
            # naive overlap check: if theory slot index inside lab session slot indices
            # (this is illustrative — real scheduler uses time ranges)
            if any(t_idx in s for s in [info['slots']]):
                mapping.setdefault(name, []).append(t_idx)
    return theory_slots, lab_slots, lab_sessions, mapping


def main():
    theory, lab, lab_sessions, mapping = build_time_config()
    print('02_time_config: demo')
    print('Theory slots:', len(theory))
    print('Lab sessions:', lab_sessions)
    print('Mapping (lab session -> theory slot indices):', mapping)

if __name__ == '__main__':
    main()
