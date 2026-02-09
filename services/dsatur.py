from collections import defaultdict
import random

def build_conflict_graph(sessions):
    """
    Builds a conflict graph where nodes are session indices and edges represent conflicts.
    Node: session index
    Edge if:
      - same batch
      - same faculty (intersection of faculty pools, though actual conflict depends on assignment. 
        For DSATUR/Pre-coloring, we assume worst case or shared resource)
      - For Timetabling, usually 'Same Batch' is a clique. 
      - 'Same Faculty' is a potential conflict.
    """
    graph = defaultdict(set)
    n = len(sessions)

    for i in range(n):
        for j in range(i+1, n):
            s1, s2 = sessions[i], sessions[j]
            conflict = False

            # 1. Same Batch (Hard Conflict - cannot be in same slot)
            if s1['batch_id'] == s2['batch_id']:
                conflict = True

            # 2. Shared Faculty Resource
            # Heuristic: If they share ANY qualified faculty, there is a potential conflict.
            # Stronger: If they share the SAME faculty pool exactly.
            # For DSATUR, we want to color 'conflicting' nodes differently.
            # If two sessions *could* take the same faculty, we ideally don't want them in parallel
            # if we are limited on faculty.
            # But availability is dynamic.
            # Let's stick to 'Same Batch' as primary hard conflict for graph structure.
            # And 'overlapping faculty pool' as secondary.
            
            pool1 = set(f['_id'] for f in s1['faculty_pool'])
            pool2 = set(f['_id'] for f in s2['faculty_pool'])
            
            # If overlap is significant (e.g. they rely on the same specialized teacher)
            if not pool1.isdisjoint(pool2):
                 # If pools are small (e.g. 1 person), this is a hard conflict.
                 if len(pool1) == 1 and len(pool2) == 1 and pool1 == pool2:
                     conflict = True
            
            if conflict:
                graph[i].add(j)
                graph[j].add(i)

    return graph

def dsatur_coloring(graph, total_nodes):
    """
    DSATUR Algorithm for Graph Coloring.
    Returns: node_index -> color_index (0..k)
    """
    colors = {}
    saturation = defaultdict(set) # node -> set of neighbor colors
    degrees = defaultdict(int)
    
    # Calculate initial degrees
    for u in range(total_nodes):
        degrees[u] = len(graph[u])

    uncolored = set(range(total_nodes))

    while uncolored:
        # Pick node with highest saturation level, then highest degree
        # Sort uncolored nodes
        # Negate saturation/degree for descending sort using min
        node = min(uncolored, key=lambda n: (-len(saturation[n]), -degrees[n]))

        uncolored.remove(node)

        # Assign smallest valid color
        neighbor_colors = saturation[node]
        color = 0
        while color in neighbor_colors:
            color += 1
            
        colors[node] = color

        # Update neighbors
        for neighbor in graph[node]:
            if neighbor in uncolored:
                saturation[neighbor].add(color)

    return colors
