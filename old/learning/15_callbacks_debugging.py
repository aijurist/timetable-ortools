"""15 — Callbacks, logging and debugging techniques

Shows how to use solution callbacks, logging intermediate solutions, and simple
instrumentation to time model build and solve. Also includes tips for isolating
problematic constraints.
"""
from ortools.sat.python import cp_model
import time

class PrintCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, vars):
        super().__init__()
        self._vars = vars
        self._count = 0
    def OnSolutionCallback(self):
        self._count += 1
        print(f'  callback solution #{self._count}')


def main():
    print('15_callbacks_debugging: demo')
    t0 = time.time()
    model = cp_model.CpModel()
    x = [model.NewBoolVar(f'x{i}') for i in range(20)]
    model.Add(sum(x) >= 5)
    model.Maximize(sum(x))
    t1 = time.time()
    print('  build time (s):', round(t1 - t0, 3))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2
    cb = PrintCallback(x)
    status = solver.SolveWithSolutionCallback(model, cb)
    t2 = time.time()
    print('  solve time (s):', round(t2 - t1, 3))
    print('  callback solutions seen:', cb._count)

if __name__ == '__main__':
    main()
