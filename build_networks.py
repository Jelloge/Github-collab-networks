import json
import os
import csv
from collections import defaultdict

DATA_DIR = "data"
OUT_DIR = "networks"

# explicit denylist of service/automation accounts
# using exact usernames only (no substring matching) to avoid
# accidentally removing real users like cassiobotaro
BLOCKLIST = {
    "copilot-pull-request-reviewer",
    "copilot-swe-agent",
    "astral-sh-bot",
    "snyk-io",
    "codspeed-hq",
    "renovate-bot",
    "google-wombot",
    # these were missing and showing up in edge lists
    "github-actions",
    "dependabot",
    "pre-commit-ci",
    "renovate",
    "copilot",
    "codecov",
    "askdevai-bot",
    "ercbot",
    "klim4-bot",
    "cursor",
}

#labels that usually mean its a dependency/automated PR
DEP_LABELS = {"dependencies", "dependency", "deps", "renovate", "dependabot"}

REPO_FILES = {
    "vscode-pr-github": "microsoft_vscode-pull-request-github.json",
    "ruff": "astral-sh_ruff.json",
    "streamlit": "streamlit_streamlit.json",
    "fastapi": "fastapi_fastapi.json",
}


def is_blocked(login, is_bot_flag=False):
    """check if a login should be filtered out.
    uses both the explicit denylist and the is_bot flag already tagged in the json"""
    if not login:
        return True
    if is_bot_flag:
        return True
    lower = login.lower()
    if lower.endswith("[bot]"):
        return True
    if lower in BLOCKLIST:
        return True
    return False


def is_dep_pr(pr):
    """check if PR is a dependency update based on labels"""
    labels = {l.lower() for l in pr.get("labels", [])}
    return bool(labels & DEP_LABELS)


def find_suspicious_accounts(prs):
    user_stats = defaultdict(lambda: {
        "review_states": [],
        "comment_count": 0,
        "dep_pr_interactions": 0,
        "total_interactions": 0,
        "authored_prs": 0,
        "dep_authored": 0,
    })

    for pr in prs:
        author = pr.get("author")
        if not author or is_blocked(author):
            continue

        dep = is_dep_pr(pr)
        user_stats[author]["authored_prs"] += 1
        if dep:
            user_stats[author]["dep_authored"] += 1

        for r in pr.get("reviews", []):
            login = r.get("login")
            if not login or is_blocked(login):
                continue
            user_stats[login]["review_states"].append(r["state"])
            user_stats[login]["total_interactions"] += 1
            if dep:
                user_stats[login]["dep_pr_interactions"] += 1

        for c in pr.get("comments", []):
            login = c.get("login")
            if not login or is_blocked(login):
                continue
            user_stats[login]["comment_count"] += 1
            user_stats[login]["total_interactions"] += 1
            if dep:
                user_stats[login]["dep_pr_interactions"] += 1

    suspicious = []
    for user, stats in user_stats.items():
        reasons = []

        #only approved review and not  commented
        if (stats["review_states"]
                and all(s == "APPROVED" for s in stats["review_states"])
                and stats["comment_count"] == 0
                and stats["total_interactions"] >= 3):
            reasons.append("only APPROVED reviews, zero comments")

        #only interacts with dependency PRs
        if (stats["total_interactions"] >= 3
                and stats["dep_pr_interactions"] == stats["total_interactions"]):
            reasons.append("only interacts with dependency PRs")

        #authored only dep PRs
        if (stats["authored_prs"] >= 3
                and stats["dep_authored"] == stats["authored_prs"]):
            reasons.append("only authors dependency PRs")

        if reasons:
            suspicious.append({
                "user": user,
                "reasons": reasons,
                "reviews": len(stats["review_states"]),
                "comments": stats["comment_count"],
                "total": stats["total_interactions"],
                "dep_interactions": stats["dep_pr_interactions"],
                "authored_prs": stats["authored_prs"],
                "dep_authored": stats["dep_authored"],
            })

    return suspicious


def build_edges(prs, review_weight=1, comment_weight=1):
    """build edge dict: (source, target) -> weight"""
    edges = defaultdict(int)

    for pr in prs:
        author = pr.get("author")
        if not author or is_blocked(author, pr.get("author_is_bot", False)):
            continue
        #reviews -> author
        for r in pr.get("reviews", []):
            reviewer = r.get("login")
            if not reviewer or is_blocked(reviewer, r.get("is_bot", False)):
                continue
            if reviewer == author:
                continue  # skip self-reviews
            edges[(reviewer, author)] += review_weight
        # comments -> author
        for c in pr.get("comments", []):
            commenter = c.get("login")
            if not commenter or is_blocked(commenter, c.get("is_bot", False)):
                continue
            if commenter == author:
                continue  # skip self-comments
            edges[(commenter, author)] += comment_weight
    return edges


def get_all_users(prs):
    """get set of all non-bot users who appear in any role"""
    users = set()
    for pr in prs:
        author = pr.get("author")
        if author and not is_blocked(author, pr.get("author_is_bot", False)):
            users.add(author)
        for r in pr.get("reviews", []):
            login = r.get("login")
            if login and not is_blocked(login, r.get("is_bot", False)):
                users.add(login)
        for c in pr.get("comments", []):
            login = c.get("login")
            if login and not is_blocked(login, c.get("is_bot", False)):
                users.add(login)
    return users
def write_edges_csv(edges, filepath):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["source", "target", "weight"])
        for (src, tgt), w in sorted(edges.items()):
            writer.writerow([src, tgt, w])
def write_nodes_csv(users, filepath):
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user"])
        for u in sorted(users):
            writer.writerow([u])
def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    for repo_name, filename in REPO_FILES.items():
        filepath = os.path.join(DATA_DIR, filename)
        print(f"\n{'='*60}")
        print(f"processing {repo_name} ({filename})")
        print(f"{'='*60}")

        with open(filepath, encoding="utf-8") as f:
            prs = json.load(f)

        #find sus accounts, but like make sure i account for false positives
        
        #equal weight edges review=1, comment=1
        edges_equal = build_edges(prs, review_weight=1, comment_weight=1)
        equal_path = os.path.join(OUT_DIR, f"edges_{repo_name}.csv")
        write_edges_csv(edges_equal, equal_path)
        print(f"\n  edges (equal weight): {len(edges_equal)} -> {equal_path}")

        #robustness check edges review=2, comment=1
        edges_weighted = build_edges(prs, review_weight=2, comment_weight=1)
        weighted_path = os.path.join(OUT_DIR, f"edges_{repo_name}_weighted.csv")
        write_edges_csv(edges_weighted, weighted_path)
        print(f"  edges (review=2):     {len(edges_weighted)} -> {weighted_path}")

        #node list
        users = get_all_users(prs)
        nodes_path = os.path.join(OUT_DIR, f"nodes_{repo_name}.csv")
        write_nodes_csv(users, nodes_path)
        print(f"  nodes: {len(users)} unique users -> {nodes_path}")

    print(f"\n{'='*60}")
    print(f"done! all files in {OUT_DIR}/")


if __name__ == "__main__":
    main()
