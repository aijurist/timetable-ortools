"""14 — Performance tuning for OR-Tools CP-SAT

Practical knobs and diagnostics to speed up solving:
- solver.parameters.num_search_workers
- time limit and fraction of optimality (relative gap via objective_bound?)
- variable/constraint reduction: symmetry breaking, presolve
- use of search strategies and hinting
- incremental solving and portfolio strategies

This chapter lists the common parameters and shows setting them.
"""
from ortools.sat.python import cp_model


def main():
    print('14_performance_tuning: demo')
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f'x{i}') for i in range(50)]
    model.Add(sum(x) >= 10)
    model.Maximize(sum(x))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    solver.parameters.num_search_workers = 4
    solver.parameters.random_seed = 42
    solver.parameters.maximize = True
    print('  parameters set: time=2s workers=4 seed=42')
    status = solver.Solve(model)
    print('  status', status)

if __name__ == '__main__':
    main()
