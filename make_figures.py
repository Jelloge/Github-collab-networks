import csv
import os
import math
import numpy as np
import networkx as nx
import igraph as ig
import leidenalg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

FIGS = "figures"
os.makedirs(FIGS, exist_ok=True)

REPOS = {
    "vscode-pr-github": "networks/edges_vscode-pr-github.csv",
    "ruff": "networks/edges_ruff.csv",
    "streamlit": "networks/edges_streamlit.csv",
    "fastapi": "networks/edges_fastapi.csv",
}

REPO_LABELS = {
    "vscode-pr-github": "VS Code PR",
    "ruff": "Ruff",
    "streamlit": "Streamlit",
    "fastapi": "FastAPI",
}

# colors for each community (up to 20 communities)
COMMUNITY_PALETTE = [
    "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
    "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
]

# one color per repo for the stat plots
REPO_COLORS = {
    "vscode-pr-github": "#0078d4",
    "ruff": "#d4aa00",
    "streamlit": "#ff4b4b",
    "fastapi": "#009688",
}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
})


def load_graph(path):
    G = nx.DiGraph()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            G.add_edge(row["source"], row["target"], weight=int(row["weight"]))
    return G


def gini(values):
    v = np.array(sorted(values), dtype=float)
    n = len(v)
    if n == 0 or v.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return (2 * np.sum(index * v) - (n + 1) * np.sum(v)) / (n * np.sum(v))


# load all graphs and precompute metrics
print("loading graphs...")
graphs = {}
metrics = {}

for name, path in REPOS.items():
    G = load_graph(path)
    graphs[name] = G

    bc = nx.betweenness_centrality(G, weight="weight")
    U = G.to_undirected()
    constraint = nx.constraint(U)

    # leiden communities for node coloring (matches amna's analysis)
    ig_graph = ig.Graph.from_networkx(U)
    partition = leidenalg.find_partition(ig_graph, leidenalg.ModularityVertexPartition,
                                        weights="weight", seed=42)
    node_comm = {}
    ig_names = ig_graph.vs["_nx_name"]
    for i, comm in enumerate(partition):
        for idx in comm:
            node_comm[ig_names[idx]] = i

    metrics[name] = {
        "bc": bc,
        "constraint": constraint, "communities": node_comm,
        "n_communities": len(partition),
    }
    print(f"  {name}: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")


# --- network graph visualizations (2x2 grid) ---
print("\ngenerating network visualizations...")

fig, axes = plt.subplots(2, 2, figsize=(20, 20))
fig.patch.set_facecolor("#0d1117")
axes = axes.flatten()

for idx, (name, G) in enumerate(graphs.items()):
    ax = axes[idx]
    ax.set_facecolor("#0d1117")
    ax.set_aspect("equal")

    bc = metrics[name]["bc"]
    comms = metrics[name]["communities"]
    max_bc = max(bc.values()) if bc.values() else 1

    # spring layout -- k controls spacing between nodes
    pos = nx.spring_layout(G, k=1.8/math.sqrt(max(G.number_of_nodes(), 1)),
                           iterations=80, seed=42, weight="weight")

    # draw edges first so they're behind nodes
    edge_weights = [G[u][v]["weight"] for u, v in G.edges()]
    max_ew = max(edge_weights) if edge_weights else 1
    for (u, v, d) in G.edges(data=True):
        w = d["weight"]
        alpha = 0.03 + 0.15 * (w / max_ew)
        lw = 0.3 + 1.2 * (w / max_ew)
        ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                color="white", alpha=alpha, linewidth=lw, zorder=1)

    # node size proportional to betweenness, color = community
    for node in G.nodes():
        x, y = pos[node]
        size = 15 + 600 * (bc[node] / max_bc)
        comm_id = comms.get(node, 0) % len(COMMUNITY_PALETTE)
        color = COMMUNITY_PALETTE[comm_id]
        ax.scatter(x, y, s=size, c=color, alpha=0.85, edgecolors="white",
                   linewidth=0.3, zorder=3)

    # only label the top nodes so it doesn't get too cluttered
    n_labels = min(12, max(5, G.number_of_nodes() // 10))
    top_bc = sorted(bc.items(), key=lambda t: t[1], reverse=True)[:n_labels]
    for node, val in top_bc:
        x, y = pos[node]
        fontsize = 7 + 5 * (val / max_bc)
        ax.text(x, y + 0.02, node, fontsize=fontsize, color="white",
                ha="center", va="bottom", fontweight="bold",
                path_effects=[pe.withStroke(linewidth=2, foreground="#0d1117")])

    ax.set_title(REPO_LABELS[name], fontsize=18, fontweight="bold",
                 color="white", pad=15)
    ax.set_xlim(ax.get_xlim()[0] - 0.05, ax.get_xlim()[1] + 0.05)
    ax.set_ylim(ax.get_ylim()[0] - 0.05, ax.get_ylim()[1] + 0.05)
    ax.axis("off")

plt.suptitle("Collaboration Networks — Node Size = Betweenness Centrality, Color = Community",
             fontsize=16, color="white", y=0.98, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.96])
plt.savefig(f"{FIGS}/network_graphs_all.png", dpi=200, bbox_inches="tight",
            facecolor="#0d1117")
plt.close()
print("  saved network_graphs_all.png")


# --- individual network graphs (bigger, more labels) ---
print("generating individual network graphs...")

for name, G in graphs.items():
    fig, ax = plt.subplots(figsize=(14, 14))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    bc = metrics[name]["bc"]
    comms = metrics[name]["communities"]
    max_bc = max(bc.values()) if bc.values() else 1

    pos = nx.spring_layout(G, k=2.0/math.sqrt(max(G.number_of_nodes(), 1)),
                           iterations=100, seed=42, weight="weight")

    edge_weights = [G[u][v]["weight"] for u, v in G.edges()]
    max_ew = max(edge_weights) if edge_weights else 1

    for (u, v, d) in G.edges(data=True):
        w = d["weight"]
        alpha = 0.04 + 0.2 * (w / max_ew)
        lw = 0.3 + 1.5 * (w / max_ew)
        ax.plot([pos[u][0], pos[v][0]], [pos[u][1], pos[v][1]],
                color="white", alpha=alpha, linewidth=lw, zorder=1)

    for node in G.nodes():
        x, y = pos[node]
        size = 20 + 800 * (bc[node] / max_bc)
        comm_id = comms.get(node, 0) % len(COMMUNITY_PALETTE)
        color = COMMUNITY_PALETTE[comm_id]
        ax.scatter(x, y, s=size, c=color, alpha=0.85, edgecolors="white",
                   linewidth=0.4, zorder=3)

    n_labels = min(20, max(8, G.number_of_nodes() // 8))
    top_bc = sorted(bc.items(), key=lambda t: t[1], reverse=True)[:n_labels]
    for node, val in top_bc:
        x, y = pos[node]
        fontsize = 8 + 6 * (val / max_bc)
        ax.text(x, y + 0.015, node, fontsize=fontsize, color="white",
                ha="center", va="bottom", fontweight="bold",
                path_effects=[pe.withStroke(linewidth=2.5, foreground="#0d1117")])

    ax.set_title(f"{REPO_LABELS[name]} — Collaboration Network",
                 fontsize=20, fontweight="bold", color="white", pad=20)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(f"{FIGS}/network_{name}.png", dpi=200, bbox_inches="tight",
                facecolor="#0d1117")
    plt.close()
    print(f"  saved network_{name}.png")


# --- zipf plots ---
print("generating zipf plots...")

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
for ax in (ax1, ax2):
    ax.set_facecolor("#fafafa")
    ax.grid(True, alpha=0.3, linestyle="--")

for name, G in graphs.items():
    color = REPO_COLORS[name]
    label = REPO_LABELS[name]
    in_degs = sorted([d for _, d in G.in_degree()], reverse=True)
    out_degs = sorted([d for _, d in G.out_degree()], reverse=True)
    in_nz = [d for d in in_degs if d > 0]
    out_nz = [d for d in out_degs if d > 0]

    ax1.loglog(range(1, len(in_nz)+1), in_nz, "o-", color=color,
               markersize=4, linewidth=1.8, alpha=0.85, label=label, markeredgewidth=0)
    ax2.loglog(range(1, len(out_nz)+1), out_nz, "o-", color=color,
               markersize=4, linewidth=1.8, alpha=0.85, label=label, markeredgewidth=0)

ax1.set_xlabel("Rank", fontsize=12)
ax1.set_ylabel("In-degree", fontsize=12)
ax1.set_title("In-degree (Zipf)", fontsize=14, fontweight="bold")
ax1.legend(framealpha=0.9, edgecolor="none", fontsize=10)

ax2.set_xlabel("Rank", fontsize=12)
ax2.set_ylabel("Out-degree", fontsize=12)
ax2.set_title("Out-degree (Zipf)", fontsize=14, fontweight="bold")
ax2.legend(framealpha=0.9, edgecolor="none", fontsize=10)

plt.tight_layout()
plt.savefig(f"{FIGS}/zipf_degree_distributions.png", dpi=200, bbox_inches="tight")
plt.close()
print("  saved zipf_degree_distributions.png")


# --- betweenness vs degree scatter ---
print("generating betweenness scatter plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 12))
axes = axes.flatten()

for idx, (name, G) in enumerate(graphs.items()):
    ax = axes[idx]
    ax.set_facecolor("#fafafa")
    ax.grid(True, alpha=0.2, linestyle="--")
    bc = metrics[name]["bc"]
    comms = metrics[name]["communities"]
    nodes = list(G.nodes())
    x = [G.in_degree(n) + G.out_degree(n) for n in nodes]
    y = [bc[n] for n in nodes]
    c = [COMMUNITY_PALETTE[comms.get(n, 0) % len(COMMUNITY_PALETTE)] for n in nodes]
    sizes = [25 + 120 * (bc[n] / max(bc.values())) for n in nodes]

    ax.scatter(x, y, c=c, s=sizes, alpha=0.75, edgecolors="white", linewidth=0.5, zorder=3)

    # label the top 5 so we can identify who the main brokers are
    top5 = sorted(bc.items(), key=lambda t: t[1], reverse=True)[:5]
    for node, val in top5:
        deg = G.in_degree(node) + G.out_degree(node)
        ax.annotate(node, (deg, val), fontsize=8.5, fontweight="bold",
                    xytext=(6, 6), textcoords="offset points",
                    path_effects=[pe.withStroke(linewidth=2, foreground="white")])

    ax.set_xlabel("Total Degree", fontsize=11)
    ax.set_ylabel("Betweenness Centrality", fontsize=11)
    ax.set_title(REPO_LABELS[name], fontsize=14, fontweight="bold")

plt.suptitle("Betweenness Centrality vs Degree", fontsize=16, fontweight="bold", y=1.01)
plt.tight_layout()
plt.savefig(f"{FIGS}/betweenness_vs_degree.png", dpi=200, bbox_inches="tight")
plt.close()
print("  saved betweenness_vs_degree.png")


# --- betweenness CCDF ---
print("generating betweenness CCDF...")

fig, ax = plt.subplots(figsize=(9, 5.5))
ax.set_facecolor("#fafafa")
ax.grid(True, alpha=0.3, linestyle="--")

for name in REPOS:
    bc = metrics[name]["bc"]
    vals = sorted(bc.values(), reverse=True)
    vals_nz = [v for v in vals if v > 0]
    ccdf = np.arange(1, len(vals_nz)+1) / len(bc)
    ax.loglog(vals_nz, ccdf, "o-", color=REPO_COLORS[name], markersize=4,
              linewidth=2, alpha=0.85, label=REPO_LABELS[name], markeredgewidth=0)

ax.set_xlabel("Betweenness Centrality", fontsize=12)
ax.set_ylabel("P(X ≥ x)", fontsize=12)
ax.set_title("Betweenness Centrality — Complementary CDF", fontsize=14, fontweight="bold")
ax.legend(framealpha=0.9, edgecolor="none", fontsize=10)
plt.tight_layout()
plt.savefig(f"{FIGS}/betweenness_ccdf.png", dpi=200, bbox_inches="tight")
plt.close()
print("  saved betweenness_ccdf.png")


# --- formatted table helper ---
def render_table(ax, col_labels, row_data, title, col_widths=None):
    ax.axis("off")
    ax.set_title(title, fontsize=14, fontweight="bold", pad=20, loc="left")

    table = ax.table(
        cellText=row_data,
        colLabels=col_labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.6)

    # dark header row
    for j in range(len(col_labels)):
        cell = table[0, j]
        cell.set_facecolor("#2d3748")
        cell.set_text_props(color="white", fontweight="bold", fontsize=10)
        cell.set_edgecolor("white")
        cell.set_linewidth(1.5)

    # alternating row colors
    for i in range(1, len(row_data) + 1):
        for j in range(len(col_labels)):
            cell = table[i, j]
            cell.set_facecolor("#f7fafc" if i % 2 == 0 else "white")
            cell.set_edgecolor("#e2e8f0")
            cell.set_linewidth(0.5)
            if j == 0:
                cell.set_text_props(fontweight="bold", ha="left")
            cell.set_text_props(fontsize=9.5)

    if col_widths:
        for j, w in enumerate(col_widths):
            for i in range(len(row_data) + 1):
                table[i, j].set_width(w)

    return table


# --- cross-repo comparison table ---
print("generating table figures...")
repo_names = list(REPOS.keys())

comp_data = []
for name in repo_names:
    G = graphs[name]
    bc = metrics[name]["bc"]
    n = G.number_of_nodes()
    e = G.number_of_edges()
    dens = nx.density(G)
    U = G.to_undirected()
    comps = list(nx.connected_components(U))
    giant = max(len(c) for c in comps) / n * 100
    all_degs = [G.in_degree(v) + G.out_degree(v) for v in G.nodes()]
    g = gini(all_degs)

    # top 10% of nodes by weighted degree -- what share of edges do they hold?
    total_deg = {v: G.in_degree(v, weight="weight") + G.out_degree(v, weight="weight") for v in G.nodes()}
    sorted_nodes = sorted(total_deg.items(), key=lambda x: x[1], reverse=True)
    k = max(1, int(len(sorted_nodes) * 0.1))
    top_set = {v for v, _ in sorted_nodes[:k]}
    total_w = sum(d["weight"] for _, _, d in G.edges(data=True))
    top_w = sum(d["weight"] for u, v, d in G.edges(data=True) if u in top_set or v in top_set)
    edge_share = top_w / total_w if total_w else 0

    # top 5% by betweenness
    s = sorted(bc.values(), reverse=True)
    k5 = max(1, int(len(s) * 0.05))
    bc_share = sum(s[:k5]) / sum(s) if sum(s) else 0

    # bridge-core overlap: how many top betweenness nodes are also top degree nodes?
    sorted_bc = sorted(bc.items(), key=lambda t: t[1], reverse=True)
    k_bc = max(1, int(len(sorted_bc) * 0.05))
    top_bc_set = {v for v, _ in sorted_bc[:k_bc]}
    sorted_deg = sorted({v: G.in_degree(v) + G.out_degree(v) for v in G.nodes()}.items(),
                        key=lambda x: x[1], reverse=True)
    k_deg = max(1, int(len(sorted_deg) * 0.1))
    top_deg_set = {v for v, _ in sorted_deg[:k_deg]}
    bc_deg_overlap = len(top_bc_set & top_deg_set) / len(top_bc_set) if top_bc_set else 0

    # avg constraint for top betweenness nodes
    con = metrics[name]["constraint"]
    top10_bc = sorted(bc.items(), key=lambda t: t[1], reverse=True)[:10]
    avg_c = np.nanmean([con[v] for v, _ in top10_bc if v in con and not math.isnan(con.get(v, float("nan")))])

    comp_data.append({
        "nodes": n, "edges": e, "density": f"{dens:.4f}",
        "giant": f"{giant:.1f}%", "gini": f"{g:.3f}",
        "edge_share": f"{edge_share:.1%}", "bc_share": f"{bc_share:.1%}",
        "bc_deg_overlap": f"{bc_deg_overlap:.1%}",
        "constraint": f"{avg_c:.3f}",
    })

col_labels = ["Metric", "VS Code PR", "Ruff", "Streamlit", "FastAPI"]
row_keys = [
    ("Nodes", "nodes"), ("Edges", "edges"), ("Density", "density"),
    ("Giant component %", "giant"), ("Gini coefficient", "gini"),
    ("Top-10% edge share", "edge_share"), ("Top-5% BC share", "bc_share"),
    ("Bridge-core overlap", "bc_deg_overlap"),
    ("Avg constraint (top 10 BC)", "constraint"),
]

row_data = []
for label, key in row_keys:
    row_data.append([label] + [comp_data[i][key] for i in range(4)])

fig, ax = plt.subplots(figsize=(12, 5))
render_table(ax, col_labels, row_data, "Cross-Repo Network Comparison",
             col_widths=[0.25, 0.15, 0.15, 0.15, 0.15])
plt.savefig(f"{FIGS}/table_cross_repo.png", dpi=200, bbox_inches="tight",
            facecolor="white")
plt.close()
print("  saved table_cross_repo.png")


# --- top 10 betweenness nodes per repo ---
for name in REPOS:
    bc = metrics[name]["bc"]
    con = metrics[name]["constraint"]
    G = graphs[name]
    top10 = sorted(bc.items(), key=lambda t: t[1], reverse=True)[:10]

    col_labels = ["Rank", "User", "Betweenness", "In-deg", "Out-deg", "Constraint"]
    row_data = []
    for rank, (node, val) in enumerate(top10, 1):
        c_val = con.get(node, float("nan"))
        row_data.append([
            str(rank), node, f"{val:.4f}",
            str(G.in_degree(node)), str(G.out_degree(node)),
            f"{c_val:.3f}" if not math.isnan(c_val) else "—",
        ])

    fig, ax = plt.subplots(figsize=(10, 4.5))
    render_table(ax, col_labels, row_data,
                 f"{REPO_LABELS[name]} — Top 10 Betweenness Centrality Nodes",
                 col_widths=[0.08, 0.28, 0.15, 0.1, 0.1, 0.13])
    plt.savefig(f"{FIGS}/table_top_bc_{name}.png", dpi=200, bbox_inches="tight",
                facecolor="white")
    plt.close()
    print(f"  saved table_top_bc_{name}.png")


# --- comparison bar charts (4-panel, focused on our 3 variables) ---
print("generating comparison bar charts...")

fig, axes = plt.subplots(2, 2, figsize=(13, 9))
axes = axes.flatten()
labels = [REPO_LABELS[n] for n in repo_names]
colors = [REPO_COLORS[n] for n in repo_names]

for ax in axes:
    ax.set_facecolor("#fafafa")
    ax.grid(True, axis="y", alpha=0.3, linestyle="--")

# concentration: gini
axes[0].bar(labels, [float(comp_data[i]["gini"]) for i in range(4)],
            color=colors, edgecolor="white", linewidth=2)
axes[0].set_title("Gini Coefficient (Concentration)", fontweight="bold", fontsize=12)
axes[0].set_ylim(0, 1)

# concentration: top 5% BC share
axes[1].bar(labels, [float(comp_data[i]["bc_share"].strip("%")) / 100 for i in range(4)],
            color=colors, edgecolor="white", linewidth=2)
axes[1].set_title("Top 5% Betweenness Share", fontweight="bold", fontsize=12)
axes[1].set_ylim(0, 1.1)

# bridge/core: overlap
axes[2].bar(labels, [float(comp_data[i]["bc_deg_overlap"].strip("%")) / 100 for i in range(4)],
            color=colors, edgecolor="white", linewidth=2)
axes[2].set_title("Bridge-Core Overlap", fontweight="bold", fontsize=12)
axes[2].set_ylim(0, 1.1)

# bridge/core: constraint
axes[3].bar(labels, [float(comp_data[i]["constraint"]) for i in range(4)],
            color=colors, edgecolor="white", linewidth=2)
axes[3].set_title("Avg Constraint (Top 10 BC)", fontweight="bold", fontsize=12)

for ax in axes:
    ax.tick_params(axis="x", rotation=20)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)

plt.suptitle("Cross-Repo Comparison", fontsize=17, fontweight="bold")
plt.tight_layout(rect=[0, 0, 1, 0.95])
plt.savefig(f"{FIGS}/cross_repo_comparison.png", dpi=200, bbox_inches="tight")
plt.close()
print("  saved cross_repo_comparison.png")

print(f"\ndone! {len(os.listdir(FIGS))} files in {FIGS}/")
