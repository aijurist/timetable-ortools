"""04 — Course grouping

A minimal example that splits course instances into groups and performs a simple
Hall's theorem sanity check via bipartite matching (using NetworkX).
"""
import networkx as nx


def make_groups(courses):
    # courses: list of (course_id, instances)
    groups = []
    gid = 0
    for cid, inst in courses:
        for i in range(inst):
            groups.append({'group_id': f'G{gid}', 'course_id': cid})
            gid += 1
    return groups


def halls_sanity_check(groups, rooms):
    # build bipartite graph: groups -> rooms
    G = nx.Graph()
    for g in groups:
        G.add_node(g['group_id'], bipartite=0)
    for r in rooms:
        G.add_node(r, bipartite=1)
    # naive: connect every group to every room
    for g in groups:
        for r in rooms:
            G.add_edge(g['group_id'], r)
    matching = nx.algorithms.bipartite.matching.hopcroft_karp_matching(G, top_nodes=[g['group_id'] for g in groups])
    # matching includes both sides; count matched groups
    matched_groups = [n for n in matching if n.startswith('G')]
    return len(matched_groups) == len(groups)


def main():
    print('04_groups: demo')
    courses = [('CS101', 2), ('CS102', 1)]
    groups = make_groups(courses)
    print('Groups:', groups)
    rooms = ['A101', 'A102']
    ok = halls_sanity_check(groups, rooms)
    print('Hall\'s theorem sanity check passed?', ok)

if __name__ == '__main__':
    main()
