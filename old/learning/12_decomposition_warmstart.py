"""12 — Decomposition & warm starts (labs-first warm-start pattern)

Shows the labs-first warm-start approach in miniature:
- Solve a small "lab-only" problem
- Export warm hints (assignments)
- Use hints as soft constraints in a combined model (soft-fix via penalty variables)

This is a pedagogical sketch; real warm-starts for CP-SAT are done via hints (AddHint)
or by using soft penalties to encourage keeping earlier assignments.
"""
from ortools.sat.python import cp_model


def solve_lab_only():
    model = cp_model.CpModel()
    sessions = ['S1','S2']
    rooms = ['R1','R2']
    x = {(s,r): model.NewBoolVar(f'x_{s}_{r}') for s in sessions for r in rooms}
    for s in sessions:
        model.Add(sum(x[(s,r)] for r in rooms) == 1)
    # simple objective: prefer R1
    model.Minimize(sum(x[(s,'R2')] for s in sessions))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)
    hints = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for s in sessions:
            for r in rooms:
                if solver.Value(x[(s,r)]) == 1:
                    hints[s] = r
    return hints


def combined_with_soft_fix(hints):
    model = cp_model.CpModel()
    # combined has additional groups
    sessions = ['S1','S2','S3']
    rooms = ['R1','R2']
    x = {(s,r): model.NewBoolVar(f'x_{s}_{r}') for s in sessions for r in rooms}
    for s in sessions:
        model.Add(sum(x[(s,r)] for r in rooms) == 1)
    # soft-fix: if hint exists prefer the same room via penalty
    over_pen = []
    for s, r_hint in hints.items():
        # penalty var that is 0 when assignment matches hint, 1 otherwise
        mismatch = model.NewBoolVar(f'mismatch_{s}')
        # mismatch == 1 -> assigned to a different room
        # Sum assigned to hint room >= 1 - mismatch  => if mismatch=0, must assign to hint
        model.Add(x[(s, r_hint)] >= 1 - mismatch)
        over_pen.append(mismatch)
    model.Minimize(sum(over_pen))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)
    assigned = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for s in sessions:
            for r in rooms:
                if solver.Value(x[(s,r)]) == 1:
                    assigned[s] = r
    return assigned


def main():
    print('12_decomposition_warmstart: demo')
    hints = solve_lab_only()
    print('  lab-only hints:', hints)
    assigned = combined_with_soft_fix(hints)
    print('  combined assigned (soft-fix):', assigned)

if __name__ == '__main__':
    main()
