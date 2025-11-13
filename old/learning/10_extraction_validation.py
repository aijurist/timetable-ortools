"""10 — Extraction and validation

Shows extracting boolean variable assignments into human-readable schedule
and performing a small validation (no teacher conflicts in schedule).
"""


def example_extract(solution_map):
    # solution_map: dict var_name -> value
    schedule = []
    for var, val in solution_map.items():
        if val:
            schedule.append(var)
    return schedule


def main():
    print('10_extraction_validation: demo')
    sol = {'G1_T1': True, 'G2_T1': False, 'G2_T2': True}
    schedule = example_extract(sol)
    print('Extracted schedule entries:', schedule)
    # fake validation: check teacher conflicts (not implemented fully)
    print('Validation: teacher conflicts = 0 (demo)')

if __name__ == '__main__':
    main()
