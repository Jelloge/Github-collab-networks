# for fun!!!! might be worth having for our presentation

import csv
import os
import networkx as nx
import igraph as ig
import leidenalg
from pyvis.network import Network

OUT_DIR = "interactive"
os.makedirs(OUT_DIR, exist_ok=True)

REPOS = {
    "vscode-pr-github": "networks/edges_vscode-pr-github.csv",
    "ruff": "networks/edges_ruff.csv",
    "streamlit": "networks/edges_streamlit.csv",
    "fastapi": "networks/edges_fastapi.csv",
}

# colors for communities -- tried to pick ones that look decent on dark bg
COLORS = [
    "#ff6b6b", "#4ecdc4", "#ffe66d", "#a29bfe",
    "#fd79a8", "#55efc4", "#74b9ff", "#ffeaa7",
    "#dfe6e9", "#fab1a0", "#81ecec", "#ff7675",
    "#636e72", "#00cec9", "#e17055", "#0984e3",
]


def load_graph(path):
    G = nx.DiGraph()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            G.add_edge(row["source"], row["target"], weight=int(row["weight"]))
    return G


def make_interactive(name, G):
    # get betweenness for node sizing
    bc = nx.betweenness_centrality(G, weight="weight")

    # leiden communities for coloring (same method amna uses)
    U = G.to_undirected(reciprocal=False)
    ig_graph = ig.Graph.from_networkx(U)
    partition = leidenalg.find_partition(ig_graph, leidenalg.ModularityVertexPartition,
                                        weights="weight", seed=42)
    node_comm = {}
    names = ig_graph.vs["_nx_name"]
    for i, comm in enumerate(partition):
        for idx in comm:
            node_comm[names[idx]] = i

    # pick top 60 nodes by betweenness + their neighbors, cap at 150
    sorted_nodes = sorted(bc.items(), key=lambda x: x[1], reverse=True)
    top_nodes = set()
    for node, _ in sorted_nodes[:60]:
        top_nodes.add(node)
        for neighbor in G.predecessors(node):
            top_nodes.add(neighbor)
        for neighbor in G.successors(node):
            top_nodes.add(neighbor)
        if len(top_nodes) >= 150:
            break

    sub = G.subgraph(top_nodes)

    # build pyvis network
    net = Network(height="750px", width="100%", bgcolor="#1a1a2e", font_color="white",
                  directed=True, notebook=False)
    net.barnes_hut(gravity=-3000, central_gravity=0.3, spring_length=100)

    # add nodes
    for node in sub.nodes():
        size = 10 + bc.get(node, 0) * 300
        comm_id = node_comm.get(node, 0)
        color = COLORS[comm_id % len(COLORS)]
        in_deg = G.in_degree(node, weight="weight")
        out_deg = G.out_degree(node, weight="weight")
        title = (f"<b>{node}</b><br>"
                 f"In-degree: {in_deg}<br>"
                 f"Out-degree: {out_deg}<br>"
                 f"Betweenness: {bc.get(node, 0):.4f}<br>"
                 f"Community: {comm_id}")
        net.add_node(node, label=node, size=size, color=color, title=title)

    # add edges
    for u, v, d in sub.edges(data=True):
        w = d.get("weight", 1)
        net.add_edge(u, v, value=w, color="rgba(255,255,255,0.15)")

    # save
    outpath = f"{OUT_DIR}/interactive_{name}.html"
    net.save_graph(outpath)
    print(f"saved {outpath} ({sub.number_of_nodes()} nodes, {sub.number_of_edges()} edges)")


for name, path in REPOS.items():
    G = load_graph(path)
    print(f"processing {name}...")
    make_interactive(name, G)

print("\ndone! open the html files in a browser to explore")
