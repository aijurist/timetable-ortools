"""08 — Constraint patterns

Demonstrates a few common patterns: teacher clash, capacity soft penalty (linearization sketch),
and symmetry breaking idea.
"""
from ortools.sat.python import cp_model


def main():
    print('08_constraints_patterns: demo')
    model = cp_model.CpModel()
    items = ['A','B','C']
    slots = [0,1,2]
    x = {(i,s): model.NewBoolVar(f'x_{i}_{s}') for i in items for s in slots}
    for i in items:
        model.Add(sum(x[(i,s)] for s in slots) == 1)
    # symmetry breaking: assign smallest item to smallest slot
    model.Add(x[('A',0)] == 1)
    # teacher clash example is similar to earlier chapters
    # capacity soft penalty sketch (requires integer penalty variable):
    overcap = model.NewIntVar(0, 10, 'overcap')
    # suppose sum of assigned sizes - capacity <= overcap
    # model.Add(sum(...) - capacity <= overcap)
    # objective minimize overcap
    model.Minimize(overcap)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3
    status = solver.Solve(model)
    print('Status:', status)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i in items:
            for s in slots:
                if solver.Value(x[(i,s)]) == 1:
                    print(f'{i} -> slot {s}')

if __name__ == '__main__':
    main()
