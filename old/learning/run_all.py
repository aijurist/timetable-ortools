"""Run all learning chapter demos."""
import importlib

CHAPTERS = [
    'learning.01_data_loading',
    'learning.02_time_config',
    'learning.03_rooms_groups',
    'learning.04_groups',
    'learning.05_cpsat_basics',
    'learning.06_lab_modeling',
    'learning.07_theory_modeling',
    'learning.08_constraints_patterns',
    'learning.09_solver_tips',
    'learning.10_extraction_validation',
    'learning.11_modeling_patterns',
    'learning.12_decomposition_warmstart',
    'learning.13_presolve_pruning',
    'learning.14_performance_tuning',
    'learning.15_callbacks_debugging',
    'learning.16_case_study_combined_mapping',
    'learning.17_hard_soft_constraints',
]


def run():
    print('\nRunning learning chapter demos...')
    for mod_name in CHAPTERS:
        try:
            mod = importlib.import_module(mod_name)
            print('\n' + '='*60)
            print(f"Chapter: {mod_name}")
            if hasattr(mod, 'main'):
                mod.main()
            else:
                print('  (no main function found)')
        except Exception as e:
            print(f'Error running {mod_name}: {e}')


if __name__ == '__main__':
    run()
