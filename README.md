Collaboration network analysis of GitHub pull request activity across 4 open-source repos.

## Repos

- microsoft/vscode-pull-request-github
- astral-sh/ruff
- streamlit/streamlit
- fastapi/fastapi

## Data collection

- Date range: March 28 2025 to March 28 2026 (365 day rolling window from collection date)
- Source: GitHub GraphQL API, 50 PRs at a time, order by creation date descended
- Cutoff: pagination stops once PR `createdAt` falls before the 12 month window
- Script: `collect_prs.py` (used my github token)

## Edge definition

Each directed edge goes reviewer/commenter -> PR author, representing a collaboration interaction on a pull request.

Two interaction types are counted:

**Review**  `pullRequest.reviews`  a submitted review (APPROVED, CHANGES_REQUESTED, or COMMENTED state). the top level review action, not individual inline code comments within a review
**PR discussion comment** `pullRequest.comments` comments in the main PR conversation thread. These are the same as issue style comments (the general discussion below the PR description) and NOT inline review comments on specific code lines

NOTE: inline code review comments (the ones left on specific lines during a review) are not included. i only made it so that the review submission itself and top-level discussion comments count as interactions

### Weight rule

- Default (edges_\<repo\>.csv): each review = 1, each comment = 1. Edge weight = total interaction count from user A to user B
- Robustness check (edges_\<repo\>_weighted.csv): review = 2, comment = 1. Same edges, different weights to test if conclusions hold when reviews are weighted more heavily

excluded self-interactions (unless you think we should have those)

## Bot filtering

Accounts are filtered out if their login ends in `[bot]` or appears in an explicit blocklist. I filtered out the ones that you mentioned and a few others:

`copilot-pull-request-reviewer`, `copilot-swe-agent`, `astral-sh-bot`, `snyk-io`, `codspeed-hq`, `renovate-bot`, `google-wombot`

The script also flags possibly-automated accounts (only approved reviews with zero comments, or only interacting with dependency PRs) for manual review, but doesn't auto-remove them

Bot retagging script: `retag_bots.py`
