import json
import os

# all the bot/service accounts we found in the data
# some of these are obvious (dependabot, github-actions) but others
# like astral-sh-bot or copilot-swe-agent only showed up when we
# manually looked through the author lists
BOT_ACCOUNTS = {
    "dependabot",
    "github-actions",
    "copilot",
    "renovate",
    "pre-commit-ci",
    "codecov",
    "google-wombot",
    "copilot-pull-request-reviewer",
    "copilot-swe-agent",
    "astral-sh-bot",
    "snyk-io",
    "codspeed-hq",
    "cursor",
    "askdevai-bot",
    "ercbot",
    "klim4-bot",
}

# these ppl have "bot" in their username but theyre actually humans lol
NOT_BOTS = {"cassiobotaro", "fallingbottom"}


def check_if_bot(login):
    if not login:
        return False
    name = login.lower()
    if name in NOT_BOTS:
        return False
    if name in BOT_ACCOUNTS or name.endswith("[bot]"):
        return True
    return False


def update_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        prs = json.load(f)

    count = 0
    for pr in prs:
        # check pr author
        val = check_if_bot(pr.get("author"))
        if pr.get("author_is_bot") != val:
            pr["author_is_bot"] = val
            count += 1

        # check each reviewer
        for r in pr.get("reviews", []):
            val = check_if_bot(r.get("login"))
            if r.get("is_bot") != val:
                r["is_bot"] = val
                count += 1

        # check each commenter
        for c in pr.get("comments", []):
            val = check_if_bot(c.get("login"))
            if c.get("is_bot") != val:
                c["is_bot"] = val
                count += 1

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(prs, f, indent=2, ensure_ascii=False)

    return count


if __name__ == "__main__":
    data_dir = "data"
    total = 0

    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".json") or fname == "summary.json":
            continue
        path = os.path.join(data_dir, fname)
        n = update_file(path)
        print(f"{fname}: updated {n} entries")
        total += n

    print(f"\ndone, {total} total fields retagged")
