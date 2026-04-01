import csv
import os
import math
import numpy as np
import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

OUT_DIR = "figures"
os.makedirs(OUT_DIR, exist_ok=True)

REPOS = {
    "vscode-pr-github": "networks/edges_vscode-pr-github.csv",
    "ruff": "networks/edges_ruff.csv",
    "streamlit": "networks/edges_streamlit.csv",
    "fastapi": "networks/edges_fastapi.csv",
}


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


def top_pct_edge_share(G, pct=0.1):
    """what fraction of total edge weight do the top pct% of nodes (by total degree) account for"""
    total_deg = {n: G.in_degree(n, weight="weight") + G.out_degree(n, weight="weight") for n in G.nodes()}
    sorted_nodes = sorted(total_deg.items(), key=lambda x: x[1], reverse=True)
    k = max(1, int(len(sorted_nodes) * pct))
    top_nodes = {n for n, _ in sorted_nodes[:k]}
    total_weight = sum(d["weight"] for _, _, d in G.edges(data=True))
    top_weight = sum(d["weight"] for u, v, d in G.edges(data=True) if u in top_nodes or v in top_nodes)
    return top_weight / total_weight if total_weight > 0 else 0


def betweenness_analysis(G):
    bc = nx.betweenness_centrality(G, weight="weight")
    sorted_bc = sorted(bc.items(), key=lambda x: x[1], reverse=True)
    k = max(1, int(len(sorted_bc) * 0.05))
    top5 = sorted_bc[:k]
    total_bc = sum(bc.values())
    top5_share = sum(v for _, v in top5) / total_bc if total_bc > 0 else 0

    # check overlap with top 10% by degree
    total_deg = {n: G.in_degree(n) + G.out_degree(n) for n in G.nodes()}
    sorted_deg = sorted(total_deg.items(), key=lambda x: x[1], reverse=True)
    k_deg = max(1, int(len(sorted_deg) * 0.1))
    top10_deg = {n for n, _ in sorted_deg[:k_deg]}
    top5_bc_set = {n for n, _ in top5}
    overlap = len(top5_bc_set & top10_deg) / len(top5_bc_set) if top5_bc_set else 0

    return bc, top5_share, overlap, sorted_bc[:10]


def hits_analysis(G):
    hubs, authorities = nx.hits(G, max_iter=500, tol=1e-8)
    top_hubs = sorted(hubs.items(), key=lambda x: x[1], reverse=True)[:10]
    top_auths = sorted(authorities.items(), key=lambda x: x[1], reverse=True)[:10]
    hub_set = {n for n, _ in top_hubs}
    auth_set = {n for n, _ in top_auths}
    overlap = len(hub_set & auth_set)
    return hubs, authorities, top_hubs, top_auths, overlap


def constraint_analysis(G, bc_sorted_top10):
    """compute Burt's constraint for top 10 betweenness nodes"""
    # nx.constraint works on undirected, convert
    U = G.to_undirected()
    constraints = nx.constraint(U)
    results = []
    for node, _ in bc_sorted_top10:
        c = constraints.get(node, float("nan"))
        results.append((node, c))
    return results


def print_table(headers, rows, col_width=20):
    header_line = "".join(h.ljust(col_width) for h in headers)
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print("".join(str(v).ljust(col_width) for v in row))


# ============================================================
# load all graphs
# ============================================================
graphs = {}
for name, path in REPOS.items():
    graphs[name] = load_graph(path)
    print(f"loaded {name}: {graphs[name].number_of_nodes()} nodes, {graphs[name].number_of_edges()} edges")

# ============================================================
# 1. basic network stats
# ============================================================
print("\n" + "=" * 80)
print("BASIC NETWORK STATS")
print("=" * 80)

basic_stats = {}
headers = ["Metric", "vscode-pr-github", "ruff", "streamlit", "fastapi"]
metrics = []

for name, G in graphs.items():
    n = G.number_of_nodes()
    e = G.number_of_edges()
    density = nx.density(G)
    # connected components on undirected version
    U = G.to_undirected()
    components = list(nx.connected_components(U))
    n_components = len(components)
    giant = max(len(c) for c in components) if components else 0
    giant_pct = giant / n * 100 if n > 0 else 0
    avg_in = sum(dict(G.in_degree()).values()) / n if n > 0 else 0
    avg_out = sum(dict(G.out_degree()).values()) / n if n > 0 else 0

    basic_stats[name] = {
        "nodes": n, "edges": e, "density": f"{density:.4f}",
        "components": n_components, "giant_pct": f"{giant_pct:.1f}%",
        "avg_in": f"{avg_in:.2f}", "avg_out": f"{avg_out:.2f}",
    }

stat_keys = [("nodes", "Nodes"), ("edges", "Edges"), ("density", "Density"),
             ("components", "Components"), ("giant_pct", "Giant comp %"),
             ("avg_in", "Avg in-degree"), ("avg_out", "Avg out-degree")]

rows = []
for key, label in stat_keys:
    row = [label] + [basic_stats[name][key] for name in REPOS]
    rows.append(row)

print_table(headers, rows)

# ============================================================
# 2. concentration analysis
# ============================================================
print("\n" + "=" * 80)
print("CONCENTRATION ANALYSIS")
print("=" * 80)

# zipf plots
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

concentration = {}
for name, G in graphs.items():
    in_degs = sorted([d for _, d in G.in_degree()], reverse=True)
    out_degs = sorted([d for _, d in G.out_degree()], reverse=True)

    # filter zeros for log-log
    in_nonzero = [d for d in in_degs if d > 0]
    out_nonzero = [d for d in out_degs if d > 0]

    ranks_in = np.arange(1, len(in_nonzero) + 1)
    ranks_out = np.arange(1, len(out_nonzero) + 1)

    ax1.loglog(ranks_in, in_nonzero, "o-", markersize=3, label=name, alpha=0.7)
    ax2.loglog(ranks_out, out_nonzero, "o-", markersize=3, label=name, alpha=0.7)

    # gini on total degree
    all_degs = [G.in_degree(n) + G.out_degree(n) for n in G.nodes()]
    g = gini(all_degs)
    edge_share = top_pct_edge_share(G)

    concentration[name] = {"gini": g, "top10_edge_share": edge_share}
    print(f"{name}: Gini={g:.3f}, Top 10% edge share={edge_share:.1%}")

ax1.set_xlabel("Rank")
ax1.set_ylabel("In-degree")
ax1.set_title("In-degree Zipf plot")
ax1.legend()
ax1.grid(True, alpha=0.3)

ax2.set_xlabel("Rank")
ax2.set_ylabel("Out-degree")
ax2.set_title("Out-degree Zipf plot")
ax2.legend()
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f"{OUT_DIR}/zipf_degree_distributions.png", dpi=150)
plt.close()
print(f"saved {OUT_DIR}/zipf_degree_distributions.png")

# ============================================================
# 3. betweenness centrality
# ============================================================
print("\n" + "=" * 80)
print("BETWEENNESS CENTRALITY")
print("=" * 80)

betweenness_results = {}
for name, G in graphs.items():
    bc, top5_share, deg_overlap, top10_bc = betweenness_analysis(G)
    betweenness_results[name] = {
        "bc": bc, "top5_share": top5_share,
        "deg_overlap": deg_overlap, "top10_bc": top10_bc,
    }
    print(f"\n{name}:")
    print(f"  Top 5% betweenness share: {top5_share:.1%}")
    print(f"  Fraction of top-5%-BC also in top-10% degree: {deg_overlap:.1%}")
    print(f"  Top 10 by betweenness:")
    for node, val in top10_bc:
        print(f"    {node:30s} {val:.4f}")

# ============================================================
# 4. HITS
# ============================================================
print("\n" + "=" * 80)
print("HITS ANALYSIS")
print("=" * 80)

hits_results = {}
for name, G in graphs.items():
    hubs, auths, top_hubs, top_auths, overlap = hits_analysis(G)
    hits_results[name] = {
        "hubs": hubs, "auths": auths,
        "top_hubs": top_hubs, "top_auths": top_auths, "overlap": overlap,
    }
    print(f"\n{name}:")
    print(f"  Top 10 Hubs:")
    for node, val in top_hubs:
        print(f"    {node:30s} {val:.6f}")
    print(f"  Top 10 Authorities:")
    for node, val in top_auths:
        print(f"    {node:30s} {val:.6f}")
    print(f"  Hub-Authority top-10 overlap: {overlap}/10")

# ============================================================
# 5. Burt's constraint for top 10 betweenness nodes
# ============================================================
print("\n" + "=" * 80)
print("BURT'S NETWORK CONSTRAINT (top 10 betweenness nodes)")
print("=" * 80)

constraint_results = {}
for name, G in graphs.items():
    top10_bc = betweenness_results[name]["top10_bc"]
    constraints = constraint_analysis(G, top10_bc)
    avg_constraint = np.nanmean([c for _, c in constraints])
    constraint_results[name] = {"details": constraints, "avg": avg_constraint}
    print(f"\n{name} (avg constraint: {avg_constraint:.4f}):")
    for node, c in constraints:
        print(f"    {node:30s} {c:.4f}" if not math.isnan(c) else f"    {node:30s} NaN")

# ============================================================
# 6. Spearman correlation hub vs authority scores
# ============================================================
print("\n" + "=" * 80)
print("SPEARMAN CORRELATION: Hub vs Authority scores")
print("=" * 80)

spearman_results = {}
for name in REPOS:
    hubs = hits_results[name]["hubs"]
    auths = hits_results[name]["auths"]
    nodes = list(hubs.keys())
    hub_vals = [hubs[n] for n in nodes]
    auth_vals = [auths[n] for n in nodes]
    rho, pval = spearmanr(hub_vals, auth_vals)
    spearman_results[name] = rho
    print(f"  {name}: rho={rho:.4f}, p={pval:.2e}")

# ============================================================
# 7. cross-repo comparison table
# ============================================================
print("\n" + "=" * 80)
print("CROSS-REPO COMPARISON TABLE")
print("=" * 80)

headers = ["Metric", "vscode-pr-github", "ruff", "streamlit", "fastapi"]
rows = [
    ["Nodes"] + [basic_stats[n]["nodes"] for n in REPOS],
    ["Edges"] + [basic_stats[n]["edges"] for n in REPOS],
    ["Density"] + [basic_stats[n]["density"] for n in REPOS],
    ["Giant comp %"] + [basic_stats[n]["giant_pct"] for n in REPOS],
    ["Gini coeff"] + [f"{concentration[n]['gini']:.3f}" for n in REPOS],
    ["Top-10% edge share"] + [f"{concentration[n]['top10_edge_share']:.1%}" for n in REPOS],
    ["Top-5% BC share"] + [f"{betweenness_results[n]['top5_share']:.1%}" for n in REPOS],
    ["Hub-Auth overlap"] + [f"{hits_results[n]['overlap']}/10" for n in REPOS],
    ["Avg constraint (top10 BC)"] + [f"{constraint_results[n]['avg']:.4f}" for n in REPOS],
    ["Spearman hub-auth"] + [f"{spearman_results[n]:.4f}" for n in REPOS],
]

print_table(headers, rows, col_width=22)

# save comparison table as csv too
with open(f"{OUT_DIR}/cross_repo_comparison.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
print(f"\nsaved {OUT_DIR}/cross_repo_comparison.csv")

print("\ndone!")
