import json
import os
import sys
import time
import requests
from datetime import datetime, timezone, timedelta

# grab token from env
TOKEN = os.environ.get("GITHUB_TOKEN")
if not TOKEN:
    print("error: set GITHUB_TOKEN env variable first")
    sys.exit(1)

HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Content-Type": "application/json",
}
API_URL = "https://api.github.com/graphql"

# repos we're analyzing
REPOS = [
    ("microsoft", "vscode-pull-request-github"),
    ("astral-sh", "ruff"),
    ("streamlit", "streamlit"),
    ("fastapi", "fastapi"),
]

# 12 months back from today
CUTOFF = datetime.now(timezone.utc) - timedelta(days=365)

# bot accounts - the obvious ones plus some service accounts
# we found by manually going through the data
BOT_ACCOUNTS = {
    "dependabot", "github-actions", "copilot", "renovate",
    "pre-commit-ci", "codecov", "google-wombot",
    "copilot-pull-request-reviewer", "copilot-swe-agent",
    "astral-sh-bot", "snyk-io","cursor",
    "askdevai-bot", "ercbot", "klim4-bot",
}

# these people have "bot" in their name but are real humans
NOT_BOTS = {"cassiobotaro", "fallingbottom"}


def is_bot(login):
    if not login:
        return False
    name = login.lower()
    if name in NOT_BOTS:
        return False
    return name in BOT_ACCOUNTS or name.endswith("[bot]")


# main query - gets 50 PRs at a time with reviews, comments, files
PR_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  rateLimit {
    remaining
    resetAt
  }
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        state
        createdAt
        mergedAt
        closedAt
        additions
        deletions
        changedFiles
        author { login }
        mergedBy { login }
        labels(first: 20) { nodes { name } }
        reviews(first: 50) {
          nodes { author { login } state submittedAt }
          pageInfo { hasNextPage endCursor }
        }
        comments(first: 50) {
          nodes { author { login } createdAt }
          pageInfo { hasNextPage endCursor }
        }
        files(first: 50) {
          nodes { path }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
"""

# separate queries for when reviews/comments/files have more than 50 items
REVIEWS_QUERY = """
query($owner: String!, $name: String!, $prNumber: Int!, $cursor: String) {
  rateLimit { remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $prNumber) {
      reviews(first: 50, after: $cursor) {
        nodes { author { login } state submittedAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

COMMENTS_QUERY = """
query($owner: String!, $name: String!, $prNumber: Int!, $cursor: String) {
  rateLimit { remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $prNumber) {
      comments(first: 50, after: $cursor) {
        nodes { author { login } createdAt }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""

FILES_QUERY = """
query($owner: String!, $name: String!, $prNumber: Int!, $cursor: String) {
  rateLimit { remaining resetAt }
  repository(owner: $owner, name: $name) {
    pullRequest(number: $prNumber) {
      files(first: 50, after: $cursor) {
        nodes { path }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""


def handle_rate_limit(data):
    """check if we're running low on api calls and sleep if needed"""
    rl = data.get("data", {}).get("rateLimit", {})
    remaining = rl.get("remaining", 5000)
    reset_at = rl.get("resetAt")
    if remaining < 100 and reset_at:
        reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
        wait = (reset - datetime.now(timezone.utc)).total_seconds() + 5
        if wait > 0:
            print(f"  rate limit low ({remaining} left), sleeping {wait:.0f}s...")
            time.sleep(wait)


def run_query(query, variables):
    """send graphql query, retry on 502s"""
    for attempt in range(3):
        resp = requests.post(API_URL, headers=HEADERS,
                             json={"query": query, "variables": variables})
        if resp.status_code == 502:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        data = resp.json()
        if "errors" in data:
            print(f"  graphql errors: {data['errors']}")
        handle_rate_limit(data)
        return data
    sys.exit(f"failed after 3 retries, last status: {resp.status_code}")


def paginate_subfield(owner, name, pr_num, query, field_name, extract_fn):
    """for when a PR has more than 50 reviews/comments/files"""
    items = []
    cursor = None
    has_next = True
    while has_next:
        variables = {"owner": owner, "name": name,
                     "prNumber": pr_num, "cursor": cursor}
        data = run_query(query, variables)
        field = data["data"]["repository"]["pullRequest"][field_name]
        items.extend(extract_fn(field["nodes"]))
        has_next = field["pageInfo"]["hasNextPage"]
        cursor = field["pageInfo"]["endCursor"]
    return items


def get_reviews(nodes):
    return [{
        "login": n["author"]["login"] if n.get("author") else None,
        "state": n["state"],
        "submittedAt": n["submittedAt"],
        "is_bot": is_bot(n["author"]["login"] if n.get("author") else None),
    } for n in nodes]


def get_comments(nodes):
    return [{
        "login": n["author"]["login"] if n.get("author") else None,
        "createdAt": n["createdAt"],
        "is_bot": is_bot(n["author"]["login"] if n.get("author") else None),
    } for n in nodes]


def get_files(nodes):
    return [n["path"] for n in nodes]


def collect_repo(owner, name):
    print(f"\ncollecting PRs for {owner}/{name}...")
    prs = []
    cursor = None
    has_next = True
    page = 0

    while has_next:
        page += 1
        data = run_query(PR_QUERY, {"owner": owner, "name": name, "cursor": cursor})
        pr_data = data["data"]["repository"]["pullRequests"]
        nodes = pr_data["nodes"]
        page_info = pr_data["pageInfo"]

        hit_cutoff = False
        for pr in nodes:
            created = datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
            if created < CUTOFF:
                hit_cutoff = True
                break

            author = pr["author"]["login"] if pr.get("author") else None

            # get reviews (paginate if needed)
            reviews = get_reviews(pr["reviews"]["nodes"])
            if pr["reviews"]["pageInfo"]["hasNextPage"]:
                reviews = paginate_subfield(
                    owner, name, pr["number"],
                    REVIEWS_QUERY, "reviews", get_reviews)

            # get comments
            comments = get_comments(pr["comments"]["nodes"])
            if pr["comments"]["pageInfo"]["hasNextPage"]:
                comments = paginate_subfield(
                    owner, name, pr["number"],
                    COMMENTS_QUERY, "comments", get_comments)

            # get files changed
            files = get_files(pr["files"]["nodes"]) if pr.get("files") else []
            if pr.get("files") and pr["files"]["pageInfo"]["hasNextPage"]:
                files = paginate_subfield(
                    owner, name, pr["number"],
                    FILES_QUERY, "files", get_files)

            prs.append({
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "author": author,
                "author_is_bot": is_bot(author),
                "createdAt": pr["createdAt"],
                "mergedAt": pr["mergedAt"],
                "closedAt": pr["closedAt"],
                "mergedBy": pr["mergedBy"]["login"] if pr.get("mergedBy") else None,
                "additions": pr["additions"],
                "deletions": pr["deletions"],
                "changedFiles": pr["changedFiles"],
                "labels": [l["name"] for l in pr["labels"]["nodes"]],
                "reviews": reviews,
                "comments": comments,
                "files": files,
            })

        print(f"  page {page}: {len(nodes)} PRs (total: {len(prs)})")

        if hit_cutoff:
            print(f"  hit 12-month cutoff, stopping")
            break

        has_next = page_info["hasNextPage"]
        cursor = page_info["endCursor"]

    print(f"  done: {len(prs)} PRs for {owner}/{name}")
    return prs


def make_summary(all_data):
    summary = {}
    for repo, prs in all_data.items():
        authors = set()
        reviewers = set()
        review_count = 0
        for pr in prs:
            if pr["author"]:
                authors.add(pr["author"])
            for r in pr["reviews"]:
                if r["login"]:
                    reviewers.add(r["login"])
                review_count += 1
        summary[repo] = {
            "pr_count": len(prs),
            "unique_authors": len(authors),
            "unique_reviewers": len(reviewers),
            "total_reviews": review_count,
        }
    return summary


def main():
    os.makedirs("data", exist_ok=True)

    all_data = {}
    for owner, name in REPOS:
        key = f"{owner}_{name}"
        prs = collect_repo(owner, name)
        all_data[key] = prs

        outfile = os.path.join("data", f"{key}.json")
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(prs, f, indent=2, ensure_ascii=False)
        print(f"  saved to {outfile}")

    # write summary
    summary = make_summary(all_data)
    with open(os.path.join("data", "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"\nsummary saved to data/summary.json")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
