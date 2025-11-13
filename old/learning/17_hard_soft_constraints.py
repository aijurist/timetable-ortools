"""17 — Hard vs Soft Constraints

This chapter demonstrates clear patterns for encoding hard constraints (must be
satisfied) and soft constraints (prefer to satisfy; violations penalized via
objective terms) in OR-Tools CP-SAT.

Patterns shown:
- Hard constraints: use model.Add(...) to forbid or require assignments.
- Soft constraints via boolean penalty:
    x_pref + penalty >= 1  -> if x_pref == 0 then penalty must be 1
  (penalty is minimized in the objective)
- Soft constraints via integer "overcapacity" variable:
    sum(assignments) - capacity <= over;
    over >= 0
  (minimize over * weight)

The examples are small and focused — adapt these patterns when porting from
`combined_scheduler.py` into modular `model_builder` code.
"""
from ortools.sat.python import cp_model


def example_hard_constraint():
    """Hard constraint example: teacher clash

    Two classes cannot be in the same slot if they share a teacher. Model
    enforces the rule as a hard constraint.
    """
    model = cp_model.CpModel()
    classes = ['A', 'B']
    slots = [0, 1]
    x = {(c, s): model.NewBoolVar(f'x_{c}_s{s}') for c in classes for s in slots}

    # Each class exactly one slot
    for c in classes:
        model.Add(sum(x[(c, s)] for s in slots) == 1)

    # Hard teacher-clash: classes A and B share teacher -> cannot be same slot
    for s in slots:
        model.Add(x[('A', s)] + x[('B', s)] <= 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)

    out = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in classes:
            for s in slots:
                if solver.Value(x[(c, s)]) == 1:
                    out[c] = s
    return out


def example_soft_boolean_penalty():
    """Soft constraint example: preferred slot with boolean penalty

    Class C prefers slot 0 but it's not mandatory. We add a penalty boolean
    that must be 1 if the class is not assigned to the preferred slot. We
    minimize the penalty.
    """
    model = cp_model.CpModel()
    classes = ['C', 'D']
    slots = [0, 1]
    x = {(c, s): model.NewBoolVar(f'x_{c}_s{s}') for c in classes for s in slots}

    for c in classes:
        model.Add(sum(x[(c, s)] for s in slots) == 1)

    # Soft preference: class C prefers slot 0
    pref = ( 'C', 0 )
    penalty = model.NewBoolVar('penalty_C_pref0')
    # If x[C,0] == 0 then penalty must be 1. Constraint: x + penalty >= 1
    model.Add(x[pref] + penalty >= 1)

    # Add other hard clashes to make problem interesting (C and D cannot share slot 1)
    model.Add(x[('C',1)] + x[('D',1)] <= 1)

    # Objective: minimize total penalties (we have one penalty here)
    model.Minimize(penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)

    out = {'assignments': {}, 'penalty': None}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in classes:
            for s in slots:
                if solver.Value(x[(c, s)]) == 1:
                    out['assignments'][c] = s
        out['penalty'] = solver.Value(penalty)
    return out


def example_soft_integer_overcapacity():
    """Soft capacity penalty using an integer over variable

    We allow up to capacity=1 class per slot normally; if more are assigned,
    the 'over' variable counts extra load and is penalized in the objective.
    """
    model = cp_model.CpModel()
    classes = ['E', 'F', 'G']
    slots = [0]
    x = {(c, s): model.NewBoolVar(f'x_{c}_s{s}') for c in classes for s in slots}

    # Each class must be assigned to some slot (only slot 0 available here)
    for c in classes:
        model.Add(sum(x[(c, s)] for s in slots) == 1)

    # Capacity for slot 0 is 1; allow overcapacity measured by integer var
    capacity = 1
    over = model.NewIntVar(0, len(classes), 'overcap')
    model.Add(sum(x[(c, 0)] for c in classes) - capacity <= over)
    model.Add(over >= 0)

    # Minimize over to prefer meeting capacity
    model.Minimize(over)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    status = solver.Solve(model)

    out = {'assignments': {}, 'overcap': None}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for c in classes:
            for s in slots:
                if solver.Value(x[(c, s)]) == 1:
                    out['assignments'][c] = s
        out['overcap'] = solver.Value(over)
    return out


def main():
    print('\n17_hard_soft_constraints: demo')

    hard = example_hard_constraint()
    print('\nHard constraint (teacher clash) assignments:', hard)

    soft_bool = example_soft_boolean_penalty()
    print('\nSoft boolean-penalty example assignments:', soft_bool['assignments'])
    print('Penalty value (0 = satisfied):', soft_bool['penalty'])

    soft_int = example_soft_integer_overcapacity()
    print('\nSoft integer overcapacity assignments:', soft_int['assignments'])
    print('Overcapacity value (0 = within capacity):', soft_int['overcap'])

    print('\nNotes:')
    print('- Use small boolean penalties for individual soft preferences.')
    print('- Use integer over/shortage vars for aggregating capacity or ' \
          'load-based penalties.')
    print("- Combine weighted penalties in the objective: e.g. Minimize( w1*pen1 + w2*over )")


if __name__ == '__main__':
    main()
