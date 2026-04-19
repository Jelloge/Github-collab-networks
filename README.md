# GitHub Pull Request Collaboration Networks

Collaboration network analysis of GitHub pull request activity across four open-source repositories.

## Authors

- Amna Shahbaz
- Jasmine Jamali

## Repositories Studied

- microsoft/vscode-pull-request-github
- astral-sh/ruff
- streamlit/streamlit
- fastapi/fastapi

## Data Collection

- Date range: March 28, 2025 to March 28, 2026 (365-day rolling window from collection date)
- Source: GitHub GraphQL API
- Pagination: 50 pull requests at a time, ordered by creation date descending
- Cutoff: pagination stops once PR `createdAt` falls before the 12-month window
- Script: `collect_prs.py`
- Authentication: requires a GitHub token

## Edge Definition

Each directed edge goes from reviewer/commenter to PR author, representing a collaboration interaction on a pull request.

Two interaction types are counted:

- **Review:** `pullRequest.reviews`, meaning a submitted review with an `APPROVED`, `CHANGES_REQUESTED`, or `COMMENTED` state. This counts the top-level review action, not individual inline code comments within a review.
- **PR discussion comment:** `pullRequest.comments`, meaning comments in the main PR conversation thread. These are issue-style comments in the general discussion below the PR description, not inline review comments on specific code lines.

Inline code review comments are not included. Only review submissions and top-level PR discussion comments count as interactions.

Self-interactions are excluded.

## Weight Rules

- Default edge files: `edges_<repo>.csv`
  - Each review = 1
  - Each comment = 1
  - Edge weight = total interaction count from user A to user B

- Robustness edge files: `edges_<repo>_weighted.csv`
  - Each review = 2
  - Each comment = 1
  - Same edge definition, but reviews are weighted more heavily to test whether the main conclusions are sensitive to the weighting rule.

## Bot Filtering

Accounts are filtered out if their login ends in `[bot]` or appears in an explicit blocklist.

Explicitly filtered accounts include:

- `copilot-pull-request-reviewer`
- `copilot-swe-agent`
- `astral-sh-bot`
- `snyk-io`
- `codspeed-hq`
- `renovate-bot`
- `google-wombot`

The script also flags possibly automated accounts for manual review, such as accounts that only approve reviews with zero comments or only interact with dependency PRs, but these are not automatically removed.

Bot retagging script: `retag_bots.py`

## Main Analyses

The project compares repository-level collaboration networks using:

- concentration of activity, including strength Gini and top-contributor summaries;
- Leiden community detection on undirected weighted projections;
- bridge/core overlap using strength and betweenness centrality;
- a robustness check where reviews are weighted more heavily than comments;
- a quarterly temporal check to see whether important contributors remain stable across time.

## Outputs

Generated outputs include:

- `networks/`: node and edge lists for each repository;
- `figures/`: cross-repository plots and network visualizations;
- `outputs/leiden/`: Leiden community outputs, role tables, validation notes, and robustness results;
- `outputs/temporal/`: quarterly temporal analysis outputs;
- `interactive/`: interactive HTML network visualizations.
