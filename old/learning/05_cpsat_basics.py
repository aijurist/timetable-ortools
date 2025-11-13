"""05 — CP-SAT basics (expanded and commented)

This short chapter demonstrates the essential building blocks of a CP-SAT
model using OR-Tools and explains the concepts step-by-step. The example is
intentionally tiny so you can experiment quickly.

Problem statement (toy):
- We have 3 classes (0,1,2) and 2 timeslots (0,1).
- Each class must be assigned to exactly one timeslot.
- Classes 0 and 1 cannot be scheduled in the same timeslot (conflict).
- We minimize the number of classes assigned to timeslot 1 (arbitrary objective
  to show how to set objectives).

Key concepts shown:
- Boolean decision variables for assignment: x[(class, slot)]
- Add constraints: equality (exactly one) and linear inequalities (<=)
- Build an objective function
- Configure solver parameters and interpret the solver status

Suggested experiments:
- Change the objective (maximize instead of minimize)
- Add a capacity limit per slot (e.g., at most 2 classes per slot)
- Add solver.parameters.num_search_workers to run parallel search
"""

from ortools.sat.python import cp_model


# def main():
#     """Build and solve a tiny scheduling model with detailed comments.

#     This function is safe to run repeatedly (it's deterministic if you set
#     random_seed). It prints a small assignment and the objective value.
#     """

#     print('\n05_cpsat_basics: demo (expanded comments)')

#     # Create the CP-SAT model object. This is where variables and constraints
#     # are declared. The model is only a container; the solver performs the
#     # search when we call Solve().
#     model = cp_model.CpModel()

#     # ----- Problem data (small, clear) -----
#     num_classes = 3
#     num_slots = 2
#     classes = range(num_classes)  # 0,1,2
#     slots = range(num_slots)      # 0,1

#     # ----- Decision variables -----
#     # x[(c,s)] is True iff class c is scheduled in slot s.
#     # Using a dict keyed by (class, slot) is a common pattern for assignment
#     # variables; it maps naturally to constraints and extraction code later.
#     x = {}
#     for c in classes:
#         for s in slots:
#             # NewBoolVar creates a 0/1 variable with a readable name.
#             x[(c, s)] = model.NewBoolVar(f'x_c{c}_s{s}')


    
#     # ----- Constraints -----
#     # 1) Each class must be assigned to exactly one slot.
#     #    sum_{s} x[c,s] == 1
#     for c in classes:
#         model.Add(sum(x[(c, s)] for s in slots) == 1)

#     # 2) Conflict constraint: classes 0 and 1 cannot be in the same slot.
#     #    For every slot s: x[0,s] + x[1,s] <= 1
#     #    This forbids both variables being True at the same s.
#     for s in slots:
#         model.Add(x[(0, s)] + x[(1, s)] <= 1)

#     # ----- Objective -----
#     # Example objective: minimize number of classes assigned to slot 1.
#     # This is arbitrary for illustration — replace with domain-specific goals
#     # when building real schedules (e.g., minimize teacher gaps, maximize
#     # preferred slots, minimize over-capacity penalties, etc.).
#     model.Minimize(sum(x[(c, 1)] for c in classes))

#     # ----- Solver configuration -----
#     solver = cp_model.CpSolver()
#     # Set a short time limit so the demo runs quickly; increase when testing
#     # larger instances. You can also set solver.parameters.num_search_workers
#     # to use multi-threading (useful on multi-core machines).
#     solver.parameters.max_time_in_seconds = 5

#     # Optionally set reproducible randomness for experiments:
#     # solver.parameters.random_seed = 0

#     # ----- Solve -----
#     status = solver.Solve(model)

#     # Interpret status
#     if status == cp_model.OPTIMAL:
#         print('\nSolver status: OPTIMAL (proved optimal)')
#     elif status == cp_model.FEASIBLE:
#         print('\nSolver status: FEASIBLE (found a solution, optimality not proved)')
#     else:
#         print('\nSolver status: NO SOLUTION')

#     # If we have a solution (optimal or feasible), extract and print it.
#     if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
#         print('\nAssignments:')
#         # Iterate classes then slots to present a compact mapping
#         for c in classes:
#             for s in slots:
#                 if solver.Value(x[(c, s)]) == 1:
#                     print(f'  Class {c} -> slot {s}')

#         # You can also inspect the objective value with solver.ObjectiveValue()
#         print('\nObjective value:', solver.ObjectiveValue())

#         # Quick suggestion: to add a hint (warm start), use solver.SuggestSolution
#         # or model.AddHint in newer OR-Tools versions. Hints are useful when
#         # combining staged solves (labs-first warm-starts) — see advanced chapters.
#     else:
#         print('No solution found. Try relaxing constraints or increasing time limit.')

def main():

    num_classes = 3
    num_slots = 3
    classes = range(num_classes)
    slots = range(num_slots)

    class_slot = {}

    model = cp_model.CpModel()

    for c in classes:
        for s in slots:
            class_slot[(c,s)] = model.NewBoolVar(f'x_c{c}_s{s}')

    print(class_slot)

    for c in classes:
        model.Add(sum(class_slot[c, s] for s in slots) == 1)

    for s in slots:
        model.add(class_slot[0, s] + class_slot[1, s] <= 1)

    # model.Minimize(sum(class_slot[c, 1] for c in classes))

    print(model)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10

    status = solver.solve(model)

    print(status)

    if status == cp_model.OPTIMAL:
        print('\nSolver status: OPTIMAL (proved optimal)')
    elif status == cp_model.FEASIBLE:
        print('\nSolver status: FEASIBLE (found a solution, optimality not proved)')
    
    for c in classes:
        for s in slots:
            if solver.Value(class_slot[(c,s)]) == 1:
                print(solver.Value(class_slot[(c,s)]))
                print(f'c{c} -> s{s}')

if __name__ == '__main__':
    main()
