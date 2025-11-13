"""07 — Simple theory scheduling model

Assigns groups to theory timeslots avoiding teacher clashes (small example).
"""
from ortools.sat.python import cp_model


def main():
    print('07_theory_modeling: demo')
    model = cp_model.CpModel()
    groups = ['G1', 'G2', 'G3']
    times = ['T1', 'T2']
    # teacher assignments (G1 and G2 share teacher)
    teacher_of = {'G1': 'T_A', 'G2': 'T_A', 'G3': 'T_B'}
    x = {}
    for g in groups:
        for t in times:
            x[(g, t)] = model.NewBoolVar(f'x_{g}_{t}')
    for g in groups:
        model.Add(sum(x[(g, t)] for t in times) == 1)

    #this will cause infeasible solution because we are telling the model that each times will have only one session but there are three session and two times which mean this not possible and this is a hard constraint
    # for t in times:
    #     model.Add(sum(x[(g, t)] for g in groups) == 1)

    # teacher clash: no two groups of same teacher at same time
    for t in times:
        for teacher in set(teacher_of.values()):
            group_of_teacher = [g for g in groups if teacher_of[g] == teacher]
            model.Add(sum(x[(g,t)] for g in group_of_teacher) <= 1)
        
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for g in groups:
            for t in times:
                if solver.Value(x[(g, t)]) == 1:
                    print(f'{g} -> {t}')
    else:
        print('No solution')

if __name__ == '__main__':
    main()
