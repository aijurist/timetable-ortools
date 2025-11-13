"""16 — Case study: mapping `combined_scheduler.py` concepts into patterns

Walks through how parts of `combined_scheduler.py` map to modeling patterns:
- data normalization -> data loader
- lab variable creation -> session-room booleans
- group timeslot vars -> group-time booleans
- cross-system teacher constraints -> global teacher-clash constraints
- soft-fix warm start pattern

This chapter is a textual walk-through with small code snippets to illustrate mapping.
"""

def main():
    print('16_case_study_combined_mapping: demo')
    print('  This chapter explains how the monolithic CombinedScheduler maps into:')
    print('   - data_loader (CSV -> canonical IDs)')
    print('   - model_builder (create lab vars, theory vars, group-timeslot vars)')
    print('   - constraints modules (teacher clash, lunch, 5pm, shift patterns)')
    print('   - solver wrapper (parameters, time limits, callbacks)')
    print('\n  Example: lab var x[(group, lab_session, day, room)] -> boolean variables')
    print('  Example: soft-fix: mismatch var = 1 if new assignment differs from hint (penalty)')
    print('\n  See chapters 11-15 for concrete code patterns that implement these parts.')

if __name__ == '__main__':
    main()
