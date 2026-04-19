import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np

try:
    import igraph as ig
    import leidenalg
except ImportError:
    ig = None
    leidenalg = None

from build_networks import REPO_FILES, build_edges, get_all_users


DATA_DIR = "data"
OUT_DIR = "outputs/temporal"
FIG_DIR = "figures"

QUARTERS = [
    ("Q1", "2025-03-28", "2025-06-28"),
    ("Q2", "2025-06-28", "2025-09-28"),
    ("Q3", "2025-09-28", "2025-12-28"),
    ("Q4", "2025-12-28", "2026-03-29"),
]


def parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def gini(values):
    arr = np.array(sorted(values), dtype=float)
    n = len(arr)
    if n == 0 or arr.sum() == 0:
        return 0.0
    index = np.arange(1, n + 1)
    return float((2 * np.sum(index * arr) - (n + 1) * np.sum(arr)) / (n * np.sum(arr)))


def load_prs(repo):
    path = os.path.join(DATA_DIR, REPO_FILES[repo])
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def filter_prs(prs, start, end):
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    kept = []
    for pr in prs:
        created = parse_dt(pr["createdAt"])
        if start_dt <= created < end_dt:
            kept.append(pr)
    return kept


def build_graph(edges):
    graph = nx.DiGraph()
    for (source, target), weight in edges.items():
        graph.add_edge(source, target, weight=weight)
    return graph


def undirected_projection(graph):
    undirected = nx.Graph()
    for source, target, data in graph.edges(data=True):
        weight = data.get("weight", 1)
        if undirected.has_edge(source, target):
            undirected[source][target]["weight"] += weight
        else:
            undirected.add_edge(source, target, weight=weight)
    return undirected


def strength_by_node(graph):
    strengths = defaultdict(float)
    for source, target, data in graph.edges(data=True):
        weight = data.get("weight", 1)
        strengths[source] += weight
        strengths[target] += weight
    return dict(strengths)


def community_summary(undirected):
    if undirected.number_of_nodes() == 0:
        return 0, 0.0
    if undirected.number_of_edges() == 0 or ig is None or leidenalg is None:
        return undirected.number_of_nodes(), 1 / undirected.number_of_nodes()

    ig_graph = ig.Graph.from_networkx(undirected)
    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.ModularityVertexPartition,
        weights="weight",
        seed=42,
    )
    sizes = [len(comm) for comm in partition]
    return len(sizes), max(sizes) / undirected.number_of_nodes()


def top_items(mapping, n=5):
    return sorted(mapping.items(), key=lambda item: (-item[1], item[0]))[:n]


def role_overlap(strengths, betweenness):
    if not strengths or not betweenness:
        return 0, 0, 0, 0.0, 0.0
    k = max(5, math.ceil(0.10 * len(strengths)))
    k = min(k, len(strengths))
    top_core = {node for node, _ in top_items(strengths, k)}
    top_bridge = {node for node, _ in top_items(betweenness, k)}
    overlap = top_core & top_bridge
    union = top_core | top_bridge
    overlap_share = len(overlap) / len(top_core) if top_core else 0.0
    jaccard = len(overlap) / len(union) if union else 0.0
    return k, len(top_core), len(overlap), overlap_share, jaccard


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot_metric(rows, metric, ylabel, output):
    repos = list(REPO_FILES.keys())
    quarters = [q[0] for q in QUARTERS]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for repo in repos:
        values = []
        for quarter in quarters:
            match = next(
                row for row in rows if row["repo"] == repo and row["quarter"] == quarter
            )
            values.append(float(match[metric]))
        ax.plot(quarters, values, marker="o", linewidth=2, label=repo)
    ax.set_xlabel("Quarter")
    ax.set_ylabel(ylabel)
    ax.set_title(ylabel + " by Quarter")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(FIG_DIR, exist_ok=True)

    metric_rows = []
    important_rows = []

    for repo in REPO_FILES:
        prs = load_prs(repo)
        for quarter, start, end in QUARTERS:
            q_prs = filter_prs(prs, start, end)
            edges = build_edges(q_prs, review_weight=1, comment_weight=1)
            graph = build_graph(edges)
            users = get_all_users(q_prs)
            graph.add_nodes_from(users)
            undirected = undirected_projection(graph)
            undirected.add_nodes_from(users)

            strengths = strength_by_node(graph)
            for user in users:
                strengths.setdefault(user, 0.0)

            if undirected.number_of_edges() > 0:
                betweenness = nx.betweenness_centrality(undirected, weight="weight")
            else:
                betweenness = {node: 0.0 for node in undirected.nodes()}

            communities, largest_share = community_summary(undirected)
            k, core_count, overlap_count, overlap_share, jaccard = role_overlap(
                strengths, betweenness
            )

            top_strength = top_items(strengths, 1)[0] if strengths else ("", 0.0)
            top_bridge = top_items(betweenness, 1)[0] if betweenness else ("", 0.0)

            metric_rows.append(
                {
                    "repo": repo,
                    "quarter": quarter,
                    "start": start,
                    "end": end,
                    "prs": len(q_prs),
                    "nodes": len(users),
                    "edges": graph.number_of_edges(),
                    "strength_gini": f"{gini(strengths.values()):.3f}",
                    "communities": communities,
                    "largest_community_share": f"{largest_share:.3f}",
                    "top_k": k,
                    "bridge_core_overlap_count": overlap_count,
                    "bridge_core_overlap_share": f"{overlap_share:.3f}",
                    "bridge_core_jaccard": f"{jaccard:.3f}",
                    "top_strength_node": top_strength[0],
                    "top_strength": f"{top_strength[1]:.3f}",
                    "top_betweenness_node": top_bridge[0],
                    "top_betweenness": f"{top_bridge[1]:.6f}",
                }
            )

            for rank, (node, value) in enumerate(top_items(strengths, 5), start=1):
                important_rows.append(
                    {
                        "repo": repo,
                        "quarter": quarter,
                        "role_metric": "strength",
                        "rank": rank,
                        "node": node,
                        "value": f"{value:.6f}",
                    }
                )
            for rank, (node, value) in enumerate(top_items(betweenness, 5), start=1):
                important_rows.append(
                    {
                        "repo": repo,
                        "quarter": quarter,
                        "role_metric": "betweenness",
                        "rank": rank,
                        "node": node,
                        "value": f"{value:.6f}",
                    }
                )

    write_csv(
        os.path.join(OUT_DIR, "quarterly_metrics.csv"),
        metric_rows,
        [
            "repo",
            "quarter",
            "start",
            "end",
            "prs",
            "nodes",
            "edges",
            "strength_gini",
            "communities",
            "largest_community_share",
            "top_k",
            "bridge_core_overlap_count",
            "bridge_core_overlap_share",
            "bridge_core_jaccard",
            "top_strength_node",
            "top_strength",
            "top_betweenness_node",
            "top_betweenness",
        ],
    )
    write_csv(
        os.path.join(OUT_DIR, "important_users_by_quarter.csv"),
        important_rows,
        ["repo", "quarter", "role_metric", "rank", "node", "value"],
    )

    plot_metric(
        metric_rows,
        "strength_gini",
        "Strength Gini",
        os.path.join(FIG_DIR, "quarterly_strength_gini.png"),
    )
    plot_metric(
        metric_rows,
        "bridge_core_overlap_share",
        "Bridge/Core Overlap Share",
        os.path.join(FIG_DIR, "quarterly_bridge_core_overlap.png"),
    )
    plot_metric(
        metric_rows,
        "largest_community_share",
        "Largest Community Share",
        os.path.join(FIG_DIR, "quarterly_largest_community_share.png"),
    )

    print(f"wrote {OUT_DIR}/quarterly_metrics.csv")
    print(f"wrote {OUT_DIR}/important_users_by_quarter.csv")
    print("wrote quarterly figures in figures/")


if __name__ == "__main__":
    main()
