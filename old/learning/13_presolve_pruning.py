"""13 — Presolve & pruning techniques

Covers preprocessing strategies that dramatically reduce model size:
- remove impossible assignments (domain filtering)
- simple capacity checks and Hall theorem style matching
- greedy constructive heuristics to seed solver

Includes small examples and references to functions you can implement in the scheduler.
"""
import networkx as nx


def domain_filter_example(groups, rooms, allowed_map):
    # allowed_map: group -> set(rooms)
    # remove groups with empty allowed set -> infeasible
    infeasible = [g for g in groups if not allowed_map.get(g)]
    return infeasible


def halls_check(groups, rooms):
    # small example using bipartite matching
    G = nx.Graph()
    for g in groups:
        G.add_node(g, bipartite=0)
    for r in rooms:
        G.add_node(r, bipartite=1)
    for g in groups:
        for r in rooms:
            G.add_edge(g, r)
    m = nx.algorithms.bipartite.matching.hopcroft_karp_matching(G, top_nodes=groups)
    matched = [n for n in m if n in groups]
    return len(matched) == len(groups)


def main():
    print('13_presolve_pruning: demo')
    groups = ['G1','G2']
    rooms = ['R1']
    allowed = {'G1': {'R1'}, 'G2': set()}
    print('  domain infeasible groups:', domain_filter_example(groups, rooms, allowed))
    print('  halls check (should be False):', halls_check(['G1','G2'], rooms))

if __name__ == '__main__':
    main()
