#!/usr/bin/env python3
"""Create a network-style figure of top quarterly contributor roles."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "outputs" / "temporal" / "important_users_by_quarter.csv"
OUTPUT = ROOT / "figures" / "quarterly_role_network.png"

REPOS = ["vscode-pr-github", "fastapi", "ruff", "streamlit"]
QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
METRICS = [("strength", "Top Strength Role"), ("betweenness", "Top Betweenness Role")]

REPO_COLORS = {
    "vscode-pr-github": "#4C78A8",
    "fastapi": "#F58518",
    "ruff": "#54A24B",
    "streamlit": "#B279A2",
}


def load_top_users() -> dict[tuple[str, str, str], str]:
    top_users: dict[tuple[str, str, str], str] = {}
    with INPUT.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row["rank"] == "1":
                top_users[(row["repo"], row["quarter"], row["role_metric"])] = row["node"]
    return top_users


def draw_panel(ax: plt.Axes, top_users: dict[tuple[str, str, str], str], metric: str, title: str) -> None:
    ax.set_title(title, fontsize=15, fontweight="bold", pad=14)
    ax.set_xlim(-0.8, 4.8)
    ax.set_ylim(-0.45, 1.25)
    ax.axis("off")

    quarter_pos = {quarter: (i, 1.0) for i, quarter in enumerate(QUARTERS)}
    users = []
    for repo in REPOS:
        for quarter in QUARTERS:
            user = top_users[(repo, quarter, metric)]
            if user not in users:
                users.append(user)
    user_pos = {user: (i * (4 / max(1, len(users) - 1)), 0.08) for i, user in enumerate(users)}

    for quarter, (x, y) in quarter_pos.items():
        ax.scatter(x, y, s=950, color="#202124", zorder=4)
        ax.text(x, y, quarter, color="white", ha="center", va="center", fontsize=12, fontweight="bold", zorder=5)

    for user, (x, y) in user_pos.items():
        ax.scatter(x, y, s=850, color="#F7F2E8", edgecolor="#202124", linewidth=1.5, zorder=4)
        ax.text(x, y, user, color="#111111", ha="center", va="center", fontsize=9, fontweight="bold", zorder=5)

    for repo in REPOS:
        for quarter in QUARTERS:
            user = top_users[(repo, quarter, metric)]
            x1, y1 = quarter_pos[quarter]
            x2, y2 = user_pos[user]
            edge = FancyArrowPatch(
                (x1, y1 - 0.06),
                (x2, y2 + 0.08),
                arrowstyle="-",
                connectionstyle="arc3,rad=0.12",
                linewidth=2.5,
                color=REPO_COLORS[repo],
                alpha=0.82,
                zorder=2,
            )
            ax.add_patch(edge)

    legend_x = 4.35
    for i, repo in enumerate(REPOS):
        y = 1.08 - i * 0.16
        ax.plot([legend_x, legend_x + 0.18], [y, y], color=REPO_COLORS[repo], linewidth=3)
        ax.text(legend_x + 0.24, y, repo, va="center", fontsize=9)


def main() -> None:
    top_users = load_top_users()
    fig, axes = plt.subplots(2, 1, figsize=(12.5, 7.8), dpi=220)
    fig.patch.set_facecolor("#FBFAF7")
    for ax, (metric, title) in zip(axes, METRICS):
        ax.set_facecolor("#FBFAF7")
        draw_panel(ax, top_users, metric, title)

    fig.suptitle(
        "Quarterly Top-Contributor Role Network",
        fontsize=18,
        fontweight="bold",
        y=0.985,
    )
    fig.text(
        0.5,
        0.025,
        "Edges connect each quarter to the contributor who ranked highest for each repository and metric. Edge color identifies the repository.",
        ha="center",
        fontsize=10,
        color="#333333",
    )
    fig.tight_layout(rect=[0.02, 0.05, 1, 0.95], h_pad=1.8)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
