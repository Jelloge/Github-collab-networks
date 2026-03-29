# Github-collab-networks

Collaboration network analysis of GitHub pull request activity across 4 open-source repos.

## Repos

- microsoft/vscode-pull-request-github
- astral-sh/ruff
- streamlit/streamlit
- fastapi/fastapi

## Data collection

- **Date range**: March 28, 2025 to March 28, 2026 (365-day rolling window from collection date)
- **Source**: GitHub GraphQL API, paginated 50 PRs at a time, ordered by creation date descending
- **Cutoff**: pagination stops once PR `createdAt` falls before the 12-month window
- **Script**: `collect_prs.py` (requires `GITHUB_TOKEN` env var)

## Edge definition

Each directed edge goes **reviewer/commenter -> PR author**, representing a collaboration interaction on a pull request.

Two interaction types are counted:

| Type | GraphQL field | What it captures |
|------|--------------|-----------------|
| **Review** | `pullRequest.reviews` | A submitted review (APPROVED, CHANGES_REQUESTED, or COMMENTED state). This is the top-level review action, not individual inline code comments within a review. |
| **PR discussion comment** | `pullRequest.comments` | Comments in the main PR conversation thread. These are the same as issue-style comments (the general discussion below the PR description). **Not** inline review comments on specific code lines. |

**Important**: inline code review comments (the ones left on specific lines during a review) are *not* included. Only the review submission itself and top-level discussion comments count as interactions.

### Weight rule

- **Default (edges_\<repo\>.csv)**: each review = 1, each comment = 1. Edge weight = total interaction count from user A to user B.
- **Robustness check (edges_\<repo\>_weighted.csv)**: review = 2, comment = 1. Same edges, different weights to test if conclusions hold when reviews are weighted more heavily.

Self-interactions (author reviewing/commenting on their own PR) are excluded.

## Bot filtering

Accounts are filtered out if their login ends in `[bot]` or appears in an explicit blocklist:

`copilot-pull-request-reviewer`, `copilot-swe-agent`, `astral-sh-bot`, `snyk-io`, `codspeed-hq`, `renovate-bot`, `google-wombot`

The script also flags possibly-automated accounts (only APPROVED reviews with zero comments, or only interacting with dependency PRs) for manual review, but does not auto-remove them.

Bot retagging script: `retag_bots.py`

## Output files

- `data/` - raw PR JSON per repo + summary.json
- `networks/edges_<repo>.csv` - equal-weight edge list (source, target, weight)
- `networks/edges_<repo>_weighted.csv` - review=2 weighted edge list
- `networks/nodes_<repo>.csv` - unique non-bot users per repo
