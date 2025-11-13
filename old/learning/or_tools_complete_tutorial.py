"""
Google OR-Tools Complete Tutorial
--------------------------------

This tutorial provides a comprehensive guide to using Google OR-Tools' CP-SAT solver,
covering concepts from basic to advanced with detailed examples.

Author: GitHub Copilot
Date: November 1, 2025
"""

from ortools.sat.python import cp_model
import time

def basic_example_boolean():
    """
    Basic Example: Boolean Variables
    ------------------------------
    Demonstrates how to:
    1. Create a CP-SAT model
    2. Define boolean variables
    3. Add basic constraints
    4. Solve and print results
    
    Problem: Assign two boolean variables x and y such that:
    - x OR y must be True
    - x AND y cannot both be True
    """
    # Create a new model
    model = cp_model.CpModel()
    
    # Create boolean variables
    x = model.NewBoolVar('x')  # Creates a variable that can be 0 or 1
    y = model.NewBoolVar('y')
    
    # Add constraints
    model.Add(x + y >= 1)  # At least one must be true
    model.Add(x + y <= 1)  # Both cannot be true
    
    # Create solver and solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    # Print solution
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f"x = {solver.Value(x)}")
        print(f"y = {solver.Value(y)}")
    else:
        print("No solution found.")

def intermediate_example_integer():
    """
    Intermediate Example: Integer Variables and Constraints
    --------------------------------------------------
    Demonstrates:
    1. Integer variables with bounds
    2. Linear constraints
    3. Optimization objective
    
    Problem: Restaurant Table Assignment
    - Assign tables to 2 groups
    - Group 1: 2-6 people
    - Group 2: 3-8 people
    - Total capacity must be minimized
    """
    model = cp_model.CpModel()
    
    # Variables
    group1 = model.NewIntVar(2, 6, 'group1')  # Size for group 1
    group2 = model.NewIntVar(3, 8, 'group2')  # Size for group 2
    
    # Total capacity (objective to minimize)
    total = model.NewIntVar(0, 14, 'total')
    
    # Constraints
    model.Add(total == group1 + group2)  # Define total
    
    # Objective: Minimize total capacity
    model.Minimize(total)
    
    # Solve
    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL:
        print(f"Group 1 size: {solver.Value(group1)}")
        print(f"Group 2 size: {solver.Value(group2)}")
        print(f"Total capacity: {solver.Value(total)}")

# def advanced_example_scheduling():
#     """
#     Advanced Example: Job Scheduling with Resources
#     -------------------------------------------
#     Demonstrates:
#     1. Complex variable relationships
#     2. Interval variables
#     3. Resource constraints
#     4. Custom solution printer
    
#     Problem: Schedule 3 jobs on 2 machines
#     - Each job has a duration
#     - Jobs cannot overlap on the same machine
#     - Some jobs must finish before others can start
#     """
#     model = cp_model.CpModel()
    
#     # Data
#     jobs_data = [
#         {'name': 'Job1', 'duration': 2},
#         {'name': 'Job2', 'duration': 3},
#         {'name': 'Job3', 'duration': 4},
#     ]
#     num_machines = 2
#     horizon = sum(job['duration'] for job in jobs_data)
    
#     # Variables
#     jobs = {}
#     for job in jobs_data:
#         for machine in range(num_machines):
#             suffix = f'_{job["name"]}_machine_{machine}'
            
#             # Start time variable
#             start = model.NewIntVar(0, horizon, 'start' + suffix)
            
#             # Duration (constant)
#             duration = job['duration']
            
#             # End time variable
#             end = model.NewIntVar(0, horizon, 'end' + suffix)
            
#             # Boolean indicating if job runs on this machine
#             is_present = model.NewBoolVar('is_present' + suffix)

#             # Optional interval variable: present only when is_present == 1
#             # NewOptionalIntervalVar signature: (start, size, end, is_present, name)
#             interval = model.NewOptionalIntervalVar(start, duration, end, is_present, 'interval' + suffix)

#             jobs[job['name'], machine] = {
#                 'start': start,
#                 'duration': duration,
#                 'end': end,
#                 'interval': interval,
#                 'is_present': is_present
#             }
    
#     # Constraints
    
#     # Each job must be assigned to exactly one machine
#     for job in jobs_data:
#         model.Add(sum(jobs[job['name'], machine]['is_present'] 
#                      for machine in range(num_machines)) == 1)
    
#     # Jobs can't overlap on the same machine
#     for machine in range(num_machines):
#         intervals = []
#         for job in jobs_data:
#             # 'interval' is already an optional interval created above, so
#             # we can append it directly to the list for AddNoOverlap.
#             interval = jobs[job['name'], machine]['interval']
#             intervals.append(interval)
#         model.AddNoOverlap(intervals)
    
#     # Job2 must finish before Job3 starts
#     for m1 in range(num_machines):
#         for m2 in range(num_machines):
#             job2 = jobs['Job2', m1]
#             job3 = jobs['Job3', m2]
            
#             # If Job2 is on machine m1 and Job3 is on machine m2
#             model.Add(job3['start'] >= job2['end']).OnlyEnforceIf(
#                 [job2['is_present'], job3['is_present']])
    
#     # Objective: minimize the makespan (max end time)
#     makespan = model.NewIntVar(0, horizon, 'makespan')
#     for job in jobs_data:
#         for machine in range(num_machines):
#             model.Add(makespan >= jobs[job['name'], machine]['end']).OnlyEnforceIf(
#                 jobs[job['name'], machine]['is_present'])
    
#     model.Minimize(makespan)
    
#     # Solve
#     solver = cp_model.CpSolver()
#     status = solver.Solve(model)
    
#     if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
#         print(f'Makespan: {solver.Value(makespan)}')
        
#         # Print detailed schedule
#         for job in jobs_data:
#             for machine in range(num_machines):
#                 if solver.Value(jobs[job['name'], machine]['is_present']):
#                     start = solver.Value(jobs[job['name'], machine]['start'])
#                     print(f'{job["name"]} starts at {start} on Machine {machine}')

def advanced_example_scheduling():
    """
    Advanced Example: Job Scheduling with Resources
    -------------------------------------------
    Demonstrates:
    1. Complex variable relationships
    2. Interval variables
    3. Resource constraints
    4. Custom solution printer
    
    Problem: Schedule 3 jobs on 2 machines
    - Each job has a duration
    - Jobs cannot overlap on the same machine
    - Some jobs must finish before others can start
    """
    model = cp_model.CpModel()
    
    # Data
    jobs_data = [
        {'name': 'Job1', 'duration': 2},
        {'name': 'Job2', 'duration': 6},
        {'name': 'Job3', 'duration': 4},
    ]
    num_machines = 2
    horizon = sum(job['duration'] for job in jobs_data)

    jobs = {}

    for job in jobs_data:
        for machine in range(num_machines):
            suffix = f"_job_{job['name']}_machine_{machine}"
            start = model.NewIntVar(0, horizon, 'start'+suffix)
            duration = job['duration']
            end = model.NewIntVar(0, horizon, 'end'+suffix)
            is_present = model.NewBoolVar('is_present'+suffix)
            interval = model.NewOptionalIntervalVar(start,duration,end,is_present, 'interval'+suffix)

            jobs[job['name'],machine] = {
                'start':start,
                'end': end,
                'duration': duration,
                'interval': interval,
                'is_present':is_present
            }

    for job in jobs_data:
        model.Add(sum(jobs[job['name'],machine]['is_present'] for machine in range(num_machines)) == 1)

    for machine in range(num_machines):
        intervals = []
        for job in jobs_data:
            intervals.append(jobs[job['name'], machine]['interval'])

        model.AddNoOverlap(intervals)

    for m1 in range(num_machines):
        for m2 in range(num_machines):
            job2 = jobs['Job2', m1]
            job3 = jobs['Job3', m2]
            
            model.Add(job3['start'] >= job2['end']).OnlyEnforceIf(
                [job2['is_present'], job3['is_present']])
        
    makespan = model.NewIntVar(0, horizon, 'makespan')

    for job in jobs_data:
        for machine in range(num_machines):
                model.Add(makespan >= jobs[job['name'],machine]['end']).OnlyEnforceIf(jobs[job['name'],machine]['is_present'])


    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    status = solver.Solve(model)
    
    if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
        print(f'Makespan: {solver.Value(makespan)}')
        
        # Print detailed schedule
        for job in jobs_data:
            for machine in range(num_machines):
                if solver.Value(jobs[job['name'], machine]['is_present']):
                    start = solver.Value(jobs[job['name'], machine]['start'])
                    print(f'{job["name"]} starts at {start} on Machine {machine}')

def expert_example_custom_search():
    """
    Expert Example: Custom Search Strategies
    ------------------------------------
    Demonstrates:
    1. Custom search heuristics
    2. Solution callbacks
    3. Time limits
    4. Multiple solutions
    
    Problem: Find all valid Sudoku configurations for a partially filled grid
    """
    class SolutionPrinter(cp_model.CpSolverSolutionCallback):
        """Print intermediate solutions."""
        
        def __init__(self, variables, limit):
            cp_model.CpSolverSolutionCallback.__init__(self)
            self.__variables = variables
            self.__solution_count = 0
            self.__solution_limit = limit

        def on_solution_callback(self):
            self.__solution_count += 1
            print(f'Solution {self.__solution_count}:')
            for v in self.__variables:
                print(f'{v.Name()} = {self.Value(v)}')
            if self.__solution_count >= self.__solution_limit:
                self.StopSearch()

        def solution_count(self):
            return self.__solution_count

    # Create model
    model = cp_model.CpModel()
    
    # Example: 3x3 mini-sudoku with some filled cells
    grid_size = 3
    cells = {}
    
    # Create variables
    for i in range(grid_size):
        for j in range(grid_size):
            cells[(i, j)] = model.NewIntVar(1, grid_size, f'cell_{i}_{j}')
    
    # Add row constraints
    for i in range(grid_size):
        model.AddAllDifferent([cells[(i, j)] for j in range(grid_size)])
    
    # Add column constraints
    for j in range(grid_size):
        model.AddAllDifferent([cells[(i, j)] for i in range(grid_size)])
    
    # Pre-fill some cells
    model.Add(cells[(0, 0)] == 1)
    model.Add(cells[(1, 1)] == 2)
    
    # Create solver with time limit
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0  # 10 second time limit
    
    # Search for multiple solutions
    solution_printer = SolutionPrinter(
        variables=[cells[(i, j)] for i in range(grid_size) for j in range(grid_size)],
        limit=5)  # Limit to 5 solutions
    
    # Solve
    status = solver.SearchForAllSolutions(model, solution_printer)
    
    # Print statistics
    print('\nStatistics:')
    print(f'  status   : {solver.StatusName(status)}')
    print(f'  conflicts: {solver.NumConflicts()}')
    print(f'  branches : {solver.NumBranches()}')
    print(f'  wall time: {solver.WallTime()} s')
    print(f'  solutions found: {solution_printer.solution_count()}')

def run_all_examples():
    """Run all tutorial examples in sequence with headers and timing."""
    examples = [
        (basic_example_boolean, "Basic Example: Boolean Variables"),
        (intermediate_example_integer, "Intermediate Example: Integer Variables"),
        (advanced_example_scheduling, "Advanced Example: Job Scheduling"),
        (expert_example_custom_search, "Expert Example: Custom Search Strategies"),
    ]
    
    for func, title in examples:
        print("\n" + "="*80)
        print(f"\n{title}\n" + "-"*len(title))
        start_time = time.time()
        func()
        end_time = time.time()
        print(f"\nExample completed in {end_time - start_time:.2f} seconds")
        print("\n" + "="*80)

if __name__ == '__main__':
    run_all_examples()