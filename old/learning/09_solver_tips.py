"""09 — Solver tips

Shows how to set common CP-SAT solver parameters and use a simple solution callback
for logging intermediate solutions.
"""
from ortools.sat.python import cp_model

class SimpleCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, vars_list):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._vars = vars_list
        self._solution_count = 0
    def OnSolutionCallback(self):
        self._solution_count += 1
        print(f'  Intermediate solution {self._solution_count}')


def main():
    print('09_solver_tips: demo')
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f'x{i}') for i in range(5)]
    model.Add(sum(x) >= 2)
    model.Maximize(sum(x))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 3
    solver.parameters.num_search_workers = 8
    callback = SimpleCallback(x)
    status = solver.SolveWithSolutionCallback(model, callback)
    print('Solve status:', status)
    print('Best objective:', solver.ObjectiveValue())

if __name__ == '__main__':
    main()
