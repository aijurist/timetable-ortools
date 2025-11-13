"""11 — Modeling patterns (basic -> advanced)

Covers useful recurring modeling techniques for CP-SAT used in large schedulers:
- boolean encoding for assignments
- exactly/at-most/at-least constraints
- linearization of conditional penalties (big-M via auxiliary vars)
- symmetry breaking
- grouping and decomposition-friendly variable layouts

Each pattern includes a small runnable example.
"""
from ortools.sat.python import cp_model


def exact_one_example():
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f'x{i}') for i in range(4)]
    # exactly one true
    model.Add(sum(x) == 1)
    return model, x


def linearize_penalty_example():
    model = cp_model.CpModel()
    # Suppose we have int load and capacity; penalize over-capacity
    load = model.NewIntVar(0, 10, 'load')
    cap = 6
    over = model.NewIntVar(0, 10, 'over')
    model.Add(load - cap <= over)
    model.Add(over >= 0)
    # objective minimize over
    model.Minimize(over)
    return model, (load, over)


def symmetry_break_example():
    model = cp_model.CpModel()
    # Two identical machines; place jobs with ordering to break symmetry
    a = model.NewBoolVar('a')
    b = model.NewBoolVar('b')
    # force a <= b lexicographic style -> a implies b
    model.Add(a <= b)
    return model, (a, b)


def main():
    print('11_modeling_patterns: demo')
    m1, x = exact_one_example()
    print('  exact-one model built with', len(x), 'bools')
    m2, (load, over) = linearize_penalty_example()
    print('  linearize penalty model built (vars:', load.Name(), over.Name(), ')')
    m3, (a, b) = symmetry_break_example()
    print('  symmetry-break model built (vars:', a.Name(), b.Name(), ')')

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5

    status = solver.solve(m2)
    print(status)

    if status == cp_model.OPTIMAL:
        print('  optimal load:', solver.Value(load))
        print('  optimal overcap:', solver.Value(over))

if __name__ == '__main__':
    main()
