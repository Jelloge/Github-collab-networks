import csv
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs" / "leiden"
os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".mplconfig"))

import igraph as ig
import leidenalg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import pandas as pd


NETWORK_DIR = ROOT / "networks"
DATA_DIR = ROOT / "data"

REPO_DATA = {
    "vscode-pr-github": DATA_DIR / "microsoft_vscode-pull-request-github.json",
    "ruff": DATA_DIR / "astral-sh_ruff.json",
    "streamlit": DATA_DIR / "streamlit_streamlit.json",
    "fastapi": DATA_DIR / "fastapi_fastapi.json",
}

SCHEMES = {
    "main": "",
    "robustness": "_weighted",
}

TOP_NETWORK_REPOS = {"ruff", "vscode-pr-github", "streamlit", "fastapi"}
TOP_N_NODES = 40
ROLE_TOP_FRAC = 0.1
ROLE_TOP_MIN = 5
SEED = 42


def ensure_dirs():
    for subdir in [
        OUT_DIR,
        OUT_DIR / "tables",
        OUT_DIR / "figures",
        OUT_DIR / "community_notes",
    ]:
        subdir.mkdir(parents=True, exist_ok=True)


def load_edges(repo: str, suffix: str) -> pd.DataFrame:
    path = NETWORK_DIR / f"edges_{repo}{suffix}.csv"
    return pd.read_csv(path)


def build_undirected_projection(edges: pd.DataFrame) -> pd.DataFrame:
    pair_weights = defaultdict(float)
    for row in edges.itertuples(index=False):
        pair = tuple(sorted((row.source, row.target)))
        pair_weights[pair] += float(row.weight)
    projection = pd.DataFrame(
        [{"source": src, "target": tgt, "weight": weight} for (src, tgt), weight in pair_weights.items()]
    )
    return projection.sort_values(["weight", "source", "target"], ascending=[False, True, True]).reset_index(drop=True)


def build_graph(projection: pd.DataFrame) -> ig.Graph:
    nodes = sorted(set(projection["source"]).union(projection["target"]))
    node_index = {node: idx for idx, node in enumerate(nodes)}
    edges = [(node_index[row.source], node_index[row.target]) for row in projection.itertuples(index=False)]
    weights = [float(row.weight) for row in projection.itertuples(index=False)]

    graph = ig.Graph()
    graph.add_vertices(len(nodes))
    graph.vs["name"] = nodes
    graph.add_edges(edges)
    graph.es["weight"] = weights
    return graph


def run_leiden(graph: ig.Graph):
    partition = leidenalg.find_partition(
        graph,
        leidenalg.RBConfigurationVertexPartition,
        weights=graph.es["weight"],
        seed=SEED,
    )
    membership = partition.membership
    strengths = graph.strength(weights=graph.es["weight"])
    return membership, strengths


def write_outputs(repo: str, scheme: str, graph: ig.Graph, membership, strengths):
    scheme_suffix = "" if scheme == "main" else f"_{scheme}"
    communities = pd.DataFrame(
        {
            "node": graph.vs["name"],
            "community_id": membership,
            "strength": strengths,
        }
    ).sort_values(["community_id", "strength", "node"], ascending=[True, False, True])

    communities_path = OUT_DIR / "tables" / f"communities_{repo}{scheme_suffix}.csv"
    communities.to_csv(communities_path, index=False)

    sizes = (
        communities.groupby("community_id")
        .agg(size=("node", "count"), total_strength=("strength", "sum"))
        .reset_index()
        .sort_values(["size", "total_strength", "community_id"], ascending=[False, False, True])
    )
    sizes["share"] = sizes["size"] / len(communities)

    sizes_path = OUT_DIR / "tables" / f"community_sizes_{repo}{scheme_suffix}.csv"
    sizes.to_csv(sizes_path, index=False)
    return communities, sizes, communities_path, sizes_path


def compute_role_metrics(graph: ig.Graph) -> pd.DataFrame:
    n = graph.vcount()
    top_k = min(n, max(ROLE_TOP_MIN, math.ceil(n * ROLE_TOP_FRAC)))
    role_df = pd.DataFrame(
        {
            "node": graph.vs["name"],
            "strength": graph.strength(weights=graph.es["weight"]),
            "degree": graph.degree(),
            "betweenness": graph.betweenness(weights=graph.es["weight"], directed=False),
        }
    )
    role_df["strength_rank"] = role_df["strength"].rank(method="min", ascending=False).astype(int)
    role_df["betweenness_rank"] = role_df["betweenness"].rank(method="min", ascending=False).astype(int)
    role_df["is_core_strength"] = role_df["strength_rank"] <= top_k
    role_df["is_bridge_betweenness"] = role_df["betweenness_rank"] <= top_k
    role_df["is_bridge_and_core"] = role_df["is_core_strength"] & role_df["is_bridge_betweenness"]
    return role_df.sort_values(["strength_rank", "betweenness_rank", "node"])


def summarize_role_overlap(repo: str, role_df: pd.DataFrame):
    top_core = set(role_df.loc[role_df["is_core_strength"], "node"])
    top_bridge = set(role_df.loc[role_df["is_bridge_betweenness"], "node"])
    overlap = top_core & top_bridge
    union = top_core | top_bridge
    summary = {
        "repo": repo,
        "top_k": int(len(top_core)),
        "core_count": int(len(top_core)),
        "bridge_count": int(len(top_bridge)),
        "overlap_count": int(len(overlap)),
        "overlap_share_of_core": float(len(overlap) / len(top_core)) if top_core else 0.0,
        "overlap_share_of_bridge": float(len(overlap) / len(top_bridge)) if top_bridge else 0.0,
        "jaccard_overlap": float(len(overlap) / len(union)) if union else 0.0,
    }
    top_overlap = role_df.loc[role_df["is_bridge_and_core"], ["node", "strength", "betweenness"]].copy()
    top_overlap = top_overlap.sort_values(["betweenness", "strength", "node"], ascending=[False, False, True])
    return summary, top_overlap


def plot_role_scatter(repo: str, role_df: pd.DataFrame):
    colors = role_df["is_bridge_and_core"].map({True: "#E45756", False: "#4C78A8"})
    plt.figure(figsize=(8.8, 6.2))
    plt.scatter(
        role_df["strength"],
        role_df["betweenness"] + 1e-9,
        c=colors,
        alpha=0.75,
        s=36,
    )

    for row in role_df.nlargest(8, "betweenness").itertuples(index=False):
        plt.annotate(row.node, (row.strength, row.betweenness + 1e-9), fontsize=8, alpha=0.85)

    plt.xscale("log")
    plt.yscale("log")
    plt.xlabel("Node strength")
    plt.ylabel("Betweenness")
    plt.title(f"{repo}: bridge vs core roles")
    plt.tight_layout()
    out = OUT_DIR / "figures" / f"bridge_core_scatter_{repo}.png"
    plt.savefig(out, dpi=220)
    plt.close()
    return out


def plot_size_distribution(repo: str, sizes: pd.DataFrame, scheme: str):
    top_sizes = sizes.head(15)
    plt.figure(figsize=(9, 5))
    plt.bar(top_sizes["community_id"].astype(str), top_sizes["size"], color="#4C78A8")
    plt.title(f"{repo}: community sizes ({scheme})")
    plt.xlabel("Community ID")
    plt.ylabel("Nodes")
    plt.tight_layout()
    out = OUT_DIR / "figures" / f"community_size_distribution_{repo}_{scheme}.png"
    plt.savefig(out, dpi=220)
    plt.close()
    return out


def plot_top_nodes_network(repo: str, projection: pd.DataFrame, communities: pd.DataFrame, scheme: str):
    strength_map = communities.set_index("node")["strength"].to_dict()
    top_nodes = set(communities.nlargest(TOP_N_NODES, "strength")["node"])
    top_edges = projection[projection["source"].isin(top_nodes) & projection["target"].isin(top_nodes)].copy()
    if top_edges.empty:
        return None

    graph = nx.Graph()
    for row in top_edges.itertuples(index=False):
        graph.add_edge(row.source, row.target, weight=float(row.weight))

    node_meta = communities.set_index("node").to_dict("index")
    colors = [node_meta[node]["community_id"] for node in graph.nodes()]
    sizes = [120 + 18 * math.sqrt(node_meta[node]["strength"]) for node in graph.nodes()]
    widths = [0.4 + math.sqrt(graph[u][v]["weight"]) * 0.18 for u, v in graph.edges()]
    pos = nx.spring_layout(graph, seed=SEED, weight="weight", k=0.55)

    plt.figure(figsize=(11, 8))
    nx.draw_networkx_edges(graph, pos, alpha=0.28, width=widths, edge_color="#9E9E9E")
    nodes = nx.draw_networkx_nodes(
        graph,
        pos,
        node_color=colors,
        node_size=sizes,
        cmap=plt.cm.tab20,
        alpha=0.92,
    )
    nodes.set_edgecolor("#222222")
    nodes.set_linewidth(0.3)
    nx.draw_networkx_labels(graph, pos, font_size=8)
    plt.title(f"{repo}: top {TOP_N_NODES} nodes by strength ({scheme})")
    plt.axis("off")
    plt.tight_layout()
    out = OUT_DIR / "figures" / f"top_nodes_network_{repo}_{scheme}.png"
    plt.savefig(out, dpi=240)
    plt.close()
    return out


def coassignment_agreement(nodes, membership_a, membership_b):
    n = len(nodes)
    if n < 2:
        return 1.0
    agree = 0
    total = 0
    for i in range(n):
        for j in range(i + 1, n):
            same_a = membership_a[i] == membership_a[j]
            same_b = membership_b[i] == membership_b[j]
            agree += int(same_a == same_b)
            total += 1
    return agree / total if total else 1.0


def summarize_cross_repo(summary_rows: list[dict]):
    summary = pd.DataFrame(summary_rows).sort_values("repo")
    summary_path = OUT_DIR / "tables" / "cross_repo_community_summary.csv"
    summary.to_csv(summary_path, index=False)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    axes[0].bar(summary["repo"], summary["num_communities"], color="#72B7B2")
    axes[0].set_title("Communities by repo")
    axes[0].set_ylabel("Count")
    axes[0].tick_params(axis="x", rotation=20)

    axes[1].bar(summary["repo"], summary["largest_community_share"], color="#E45756")
    axes[1].set_title("Largest community share")
    axes[1].set_ylabel("Share of nodes")
    axes[1].tick_params(axis="x", rotation=20)

    plt.tight_layout()
    fig_path = OUT_DIR / "figures" / "cross_repo_community_comparison.png"
    plt.savefig(fig_path, dpi=220)
    plt.close()
    return summary, summary_path, fig_path


def top_path_prefix(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if not parts:
        return "(root)"
    if len(parts) >= 2 and parts[0] in {"src", "lib", "app", "packages", "crates", "tests", "docs"}:
        return "/".join(parts[:2])
    return parts[0]


def collect_user_activity(prs: list[dict]) -> dict[str, dict[str, Counter]]:
    activity = defaultdict(lambda: {"dirs": Counter(), "labels": Counter(), "prs": 0})
    for pr in prs:
        users = set()
        if pr.get("author") and not pr.get("author_is_bot", False):
            users.add(pr["author"])
        for review in pr.get("reviews", []):
            if review.get("login") and not review.get("is_bot", False):
                users.add(review["login"])
        for comment in pr.get("comments", []):
            if comment.get("login") and not comment.get("is_bot", False):
                users.add(comment["login"])

        prefixes = [top_path_prefix(path) for path in pr.get("files", [])]
        labels = [label.lower() for label in pr.get("labels", [])]
        for user in users:
            activity[user]["prs"] += 1
            activity[user]["dirs"].update(prefixes)
            activity[user]["labels"].update(labels)
    return activity


def write_validation_notes(repo: str, communities: pd.DataFrame):
    prs = json.loads(REPO_DATA[repo].read_text())
    activity = collect_user_activity(prs)

    top_communities = (
        communities.groupby("community_id")
        .size()
        .reset_index(name="size")
        .sort_values(["size", "community_id"], ascending=[False, True])
        .head(3)
    )

    lines = [f"# {repo} community validation notes", ""]
    for row in top_communities.itertuples(index=False):
        members = communities.loc[communities["community_id"] == row.community_id, "node"].tolist()
        dir_counts = Counter()
        label_counts = Counter()
        pr_total = 0
        for member in members:
            dir_counts.update(activity[member]["dirs"])
            label_counts.update(activity[member]["labels"])
            pr_total += activity[member]["prs"]

        top_dirs = ", ".join([f"{name} ({count})" for name, count in dir_counts.most_common(5)]) or "none"
        top_labels = ", ".join([f"{name} ({count})" for name, count in label_counts.most_common(5)]) or "none"
        top_members = (
            communities.loc[communities["community_id"] == row.community_id]
            .nlargest(5, "strength")["node"]
            .tolist()
        )

        lines.append(f"## Community {row.community_id}")
        lines.append(f"- Size: {row.size} nodes")
        lines.append(f"- High-strength members: {', '.join(top_members)}")
        lines.append(f"- Dominant directories/files touched: {top_dirs}")
        lines.append(f"- Dominant labels: {top_labels}")
        lines.append(f"- Interpretation: this cluster likely reflects collaborators converging around the areas above across {pr_total} PR involvements.")
        lines.append("")

    path = OUT_DIR / "community_notes" / f"{repo}_validation_notes.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_method_text(summary: pd.DataFrame, robustness_rows: list[dict]):
    method = (
        "Community detection used an undirected weighted projection of the directed collaboration network. "
        "For each pair of contributors, we summed interaction weights in both directions to represent overall collaboration intensity. "
        "We then ran Leiden community detection with the RBConfigurationVertexPartition objective and edge weights preserved."
    )
    interpretation = (
        "Community validation combined structural output with repository metadata from the underlying pull requests. "
        "For the largest communities in each repository, we compared member overlap with recurring directories and PR labels to check whether detected groups aligned with recognizable work areas or contributor subdomains."
    )

    robustness_lines = [
        "Robustness check comparing `review=1, comment=1` against `review=2, comment=1` Leiden runs:",
    ]
    for row in robustness_rows:
        robustness_lines.append(
            f"- {row['repo']}: pairwise co-assignment agreement = {row['coassignment_agreement']:.3f}, "
            f"largest community share shift = {row['largest_share_delta']:.3f}, "
            f"community count shift = {row['community_count_delta']:+d}"
        )

    largest = summary.sort_values("largest_community_share", ascending=False).iloc[0]
    smallest = summary.sort_values("largest_community_share", ascending=True).iloc[0]
    conclusion = (
        f"Across the four repositories, community structure appears in every network, but concentration differs by project. "
        f"{largest['repo']} has the most dominant largest community share ({largest['largest_community_share']:.2%}), "
        f"while {smallest['repo']} is comparatively more fragmented ({smallest['largest_community_share']:.2%}). "
        "The robustness rerun suggests the broad community picture is stable when review interactions are weighted more heavily."
    )

    text = "\n\n".join([method, interpretation, "\n".join(robustness_lines), conclusion])
    out = OUT_DIR / "community_writeup_draft.txt"
    out.write_text(text, encoding="utf-8")
    return out


def write_role_notes(role_overlap_rows: list[dict]):
    lines = [
        "Bridge/core overlap uses the undirected weighted projection for the main edge definition.",
        f'Core contributors are the top {int(ROLE_TOP_FRAC * 100)}% of nodes by strength (minimum {ROLE_TOP_MIN} nodes per repo), and bridge roles are the top nodes by betweenness using the same cutoff.',
        "Overlap is reported as counts, shares, and Jaccard similarity.",
        "",
    ]
    for row in sorted(role_overlap_rows, key=lambda item: item["repo"]):
        lines.append(
            f"- {row['repo']}: overlap={row['overlap_count']} of top {row['top_k']} "
            f"(core share={row['overlap_share_of_core']:.2%}, bridge share={row['overlap_share_of_bridge']:.2%}, "
            f"Jaccard={row['jaccard_overlap']:.3f})"
        )
    path = OUT_DIR / "bridge_core_writeup_draft.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main():
    ensure_dirs()
    os.environ.setdefault("MPLCONFIGDIR", str(OUT_DIR / ".mplconfig"))

    scheme_results = {}
    summary_rows = []
    role_overlap_rows = []

    for repo in REPO_DATA:
        scheme_results[repo] = {}
        for scheme, suffix in SCHEMES.items():
            edges = load_edges(repo, suffix)
            projection = build_undirected_projection(edges)
            graph = build_graph(projection)
            membership, strengths = run_leiden(graph)
            communities, sizes, communities_path, sizes_path = write_outputs(repo, scheme, graph, membership, strengths)

            size_fig = plot_size_distribution(repo, sizes, scheme)
            network_fig = plot_top_nodes_network(repo, projection, communities, scheme) if repo in TOP_NETWORK_REPOS else None

            scheme_results[repo][scheme] = {
                "graph": graph,
                "communities": communities,
                "sizes": sizes,
                "membership": membership,
                "strengths": strengths,
                "communities_path": communities_path,
                "sizes_path": sizes_path,
                "size_fig": size_fig,
                "network_fig": network_fig,
            }

        main_sizes = scheme_results[repo]["main"]["sizes"]
        role_df = compute_role_metrics(scheme_results[repo]["main"]["graph"])
        role_path = OUT_DIR / "tables" / f"node_roles_{repo}.csv"
        role_df.to_csv(role_path, index=False)
        role_summary, top_overlap = summarize_role_overlap(repo, role_df)
        top_overlap_path = OUT_DIR / "tables" / f"bridge_core_overlap_nodes_{repo}.csv"
        top_overlap.to_csv(top_overlap_path, index=False)
        role_scatter_path = plot_role_scatter(repo, role_df)
        role_overlap_rows.append(role_summary)

        summary_rows.append(
            {
                "repo": repo,
                "nodes": int(len(scheme_results[repo]["main"]["communities"])),
                "edges_undirected": int(scheme_results[repo]["main"]["graph"].ecount()),
                "num_communities": int(len(main_sizes)),
                "largest_community_size": int(main_sizes.iloc[0]["size"]),
                "largest_community_share": float(main_sizes.iloc[0]["share"]),
                "bridge_core_jaccard": role_summary["jaccard_overlap"],
                "bridge_core_overlap_share": role_summary["overlap_share_of_core"],
            }
        )

        write_validation_notes(repo, scheme_results[repo]["main"]["communities"])

    robustness_rows = []
    for repo in REPO_DATA:
        main_result = scheme_results[repo]["main"]
        robust_result = scheme_results[repo]["robustness"]
        nodes = main_result["graph"].vs["name"]
        robustness_rows.append(
            {
                "repo": repo,
                "coassignment_agreement": coassignment_agreement(
                    nodes,
                    main_result["membership"],
                    robust_result["membership"],
                ),
                "largest_share_delta": float(
                    robust_result["sizes"].iloc[0]["share"] - main_result["sizes"].iloc[0]["share"]
                ),
                "community_count_delta": int(len(robust_result["sizes"]) - len(main_result["sizes"])),
            }
        )

    summary, summary_path, fig_path = summarize_cross_repo(summary_rows)
    robustness_df = pd.DataFrame(robustness_rows).sort_values("repo")
    robustness_path = OUT_DIR / "tables" / "robustness_comparison.csv"
    robustness_df.to_csv(robustness_path, index=False)
    role_overlap_df = pd.DataFrame(role_overlap_rows).sort_values("repo")
    role_overlap_path = OUT_DIR / "tables" / "bridge_core_overlap_summary.csv"
    role_overlap_df.to_csv(role_overlap_path, index=False)

    draft_path = write_method_text(summary, robustness_rows)
    role_draft_path = write_role_notes(role_overlap_rows)

    manifest = {
        "summary_table": str(summary_path),
        "cross_repo_figure": str(fig_path),
        "robustness_table": str(robustness_path),
        "draft_text": str(draft_path),
        "bridge_core_table": str(role_overlap_path),
        "bridge_core_draft": str(role_draft_path),
    }
    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
