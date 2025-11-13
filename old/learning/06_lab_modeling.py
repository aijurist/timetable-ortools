"""06 — Simple lab assignment model

Shows creating session-room boolean variables and a constraint that each lab
session must be assigned to exactly one lab room. This mirrors lab variable
creation in the combined scheduler but on a tiny scale.
"""
from ortools.sat.python import cp_model


# def main():
#     print('06_lab_modeling: demo')
#     model = cp_model.CpModel()
#     sessions = ['S1', 'S2']
#     labs = ['L101', 'L102']
#     x = {}
#     for s in sessions:
#         for r in labs:
#             x[(s, r)] = model.NewBoolVar(f'x_{s}_{r}')
#     # each session to exactly one room
#     for s in sessions:
#         model.Add(sum(x[(s, r)] for r in labs) == 1)
#     # room capacity constraint (example): room L101 cannot host both sessions
#     model.Add(sum(x[(s, 'L101')] for s in sessions) <= 1)

#     solver = cp_model.CpSolver()
#     solver.parameters.max_time_in_seconds = 5
#     status = solver.Solve(model)
#     if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
#         for s in sessions:
#             assigned = [r for r in labs if solver.Value(x[(s, r)])]
#             print(f'{s} -> {assigned[0]}')
#     else:
#         print('No solution')

def main():
    labs = ['l101', 'l102', 'l103']
    sessions = ['s1', 's2', 's3']

    model = cp_model.CpModel() 

    X = {}

    for s in sessions:
        for l in labs:
            X[(s,l)] = model.NewBoolVar(f'x_s{s}_l{l}')
    

    # each session will get only one lab
    for s in sessions:
        model.Add(sum(X[(s,l)] for l in labs) <= 1)

    for l in labs:
        model.Add(sum(X[(s, l)] for s in sessions) == 1)    

    solver = cp_model.CpSolver()

    status = solver.solve(model)

    print(status)

    if status == cp_model.OPTIMAL:
        print('les go it is optimal')
    elif status == cp_model.FEASIBLE:
        print('les go it is feasiable')

    for s in sessions:
        for l in labs:
            # print(X[(s,l)])
            if solver.Value(X[(s,l)]) == 1:
                print(f'Session${s} -> Lab${l}')


if __name__ == '__main__':
    main()
