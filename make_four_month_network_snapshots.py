#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
import networkx as nx

from build_networks import REPO_FILES, build_edges, get_all_users


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT = ROOT / "figures" / "four_month_network_snapshots.png"

WINDOWS = [
    ("Mar-Jul", "2025-03-28", "2025-07-28"),
    ("Jul-Nov", "2025-07-28", "2025-11-28"),
    ("Nov-Mar", "2025-11-28", "2026-03-29"),
]

REPO_LABELS = {
    "vscode-pr-github": "VS Code PR",
    "ruff": "Ruff",
    "streamlit": "Streamlit",
    "fastapi": "FastAPI",
}

REPO_COLORS = {
    "vscode-pr-github": "#4C78A8",
    "ruff": "#54A24B",
    "streamlit": "#B279A2",
    "fastapi": "#F58518",
}


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_prs(repo: str) -> list[dict]:
    with (DATA_DIR / REPO_FILES[repo]).open(encoding="utf-8") as handle:
        return json.load(handle)


def filter_prs(prs: list[dict], start: str, end: str) -> list[dict]:
    start_dt = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    end_dt = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    return [pr for pr in prs if start_dt <= parse_dt(pr["createdAt"]) < end_dt]


def build_graph(prs: list[dict]) -> nx.DiGraph:
    edges = build_edges(prs, review_weight=1, comment_weight=1)
    graph = nx.DiGraph()
    for (source, target), weight in edges.items():
        graph.add_edge(source, target, weight=weight)
    graph.add_nodes_from(get_all_users(prs))
    return graph


def weighted_strength(graph: nx.DiGraph) -> dict[str, float]:
    strengths: dict[str, float] = defaultdict(float)
    for source, target, data in graph.edges(data=True):
        weight = data.get("weight", 1)
        strengths[source] += weight
        strengths[target] += weight
    for node in graph.nodes:
        strengths.setdefault(node, 0.0)
    return dict(strengths)


def draw_snapshot(ax: plt.Axes, repo: str, graph: nx.DiGraph, pos: dict[str, tuple[float, float]]) -> None:
    ax.set_facecolor("#0d1117")
    ax.axis("off")

    active_nodes = [node for node in graph.nodes if node in pos]
    active_edges = [(u, v, d) for u, v, d in graph.edges(data=True) if u in pos and v in pos]
    strengths = weighted_strength(graph)
    max_strength = max(strengths.values()) if strengths else 1.0
    edge_weights = [data.get("weight", 1) for _, _, data in active_edges]
    max_edge = max(edge_weights) if edge_weights else 1.0

    for source, target, data in active_edges:
        weight = data.get("weight", 1)
        x1, y1 = pos[source]
        x2, y2 = pos[target]
        ax.plot(
            [x1, x2],
            [y1, y2],
            color="white",
            alpha=0.04 + 0.20 * (weight / max_edge),
            linewidth=0.25 + 1.8 * (weight / max_edge),
            zorder=1,
        )

    color = REPO_COLORS[repo]
    for node in active_nodes:
        x, y = pos[node]
        strength = strengths.get(node, 0.0)
        size = 8 + 450 * math.sqrt(strength / max_strength) if max_strength else 8
        ax.scatter(
            x,
            y,
            s=size,
            color=color,
            alpha=0.82,
            edgecolors="white",
            linewidth=0.25,
            zorder=3,
        )

    top_nodes = sorted(strengths.items(), key=lambda item: (-item[1], item[0]))[:5]
    for node, strength in top_nodes:
        if node not in pos or strength <= 0:
            continue
        x, y = pos[node]
        ax.text(
            x,
            y + 0.02,
            node,
            fontsize=6.2,
            color="white",
            ha="center",
            va="bottom",
            fontweight="bold",
            path_effects=[pe.withStroke(linewidth=1.8, foreground="#0d1117")],
            zorder=5,
        )

    ax.text(
        0.02,
        0.98,
        f"{graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges",
        transform=ax.transAxes,
        ha="left",
        va="top",
        fontsize=7,
        color="#c9d1d9",
    )


def main() -> None:
    repos = list(REPO_FILES.keys())
    fig, axes = plt.subplots(len(repos), len(WINDOWS), figsize=(16, 14), dpi=220)
    fig.patch.set_facecolor("#0d1117")

    for row, repo in enumerate(repos):
        prs = load_prs(repo)
        full_graph = build_graph(prs)
        full_undirected = full_graph.to_undirected()
        pos = nx.spring_layout(
            full_undirected,
            seed=42,
            iterations=90,
            weight="weight",
            k=2.3 / math.sqrt(max(full_graph.number_of_nodes(), 1)),
        )

        for col, (label, start, end) in enumerate(WINDOWS):
            graph = build_graph(filter_prs(prs, start, end))
            ax = axes[row][col]
            draw_snapshot(ax, repo, graph, pos)
            if row == 0:
                ax.set_title(label, color="white", fontsize=15, fontweight="bold", pad=12)
            if col == 0:
                ax.text(
                    -0.08,
                    0.5,
                    REPO_LABELS[repo],
                    transform=ax.transAxes,
                    rotation=90,
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=15,
                    fontweight="bold",
                )

    fig.suptitle(
        "Four-Month Collaboration Network Snapshots",
        color="white",
        fontsize=20,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.02,
        "Node size = weighted strength; edge thickness = interaction weight; labels show top strength contributors in each window. Layout is fixed within each repository.",
        ha="center",
        color="#c9d1d9",
        fontsize=10,
    )
    fig.tight_layout(rect=[0.03, 0.045, 1, 0.96], h_pad=1.0, w_pad=0.6)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
