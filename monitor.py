#!/usr/bin/env python3
"""
DeepSeek GitHub Monitor (improved)

Changes made:
- Full pagination for releases and tags (like repos).
- Ensure state["releases"][repo] and state["tags"][repo] are updated to [] when there are no items.
- Improved de-dup logic: tags that correspond to releases notified in the same run (new_releases)
  will not produce duplicate notifications.
- Feishu notifications changed from plain text to rich "post" (card-like) messages with more fields.
- When possible, fetch commit details for tags to include commit message/author/date in notification.
- Minor logging improvements and safer state writes.
"""

import os
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional, Any

GITHUB_ORG = "deepseek-ai"
GITHUB_API_BASE = "https://api.github.com"
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")
STATE_FILE = "/tmp/deepseek_monitor_state.json"
PER_PAGE = 100  # pagination size


def load_state() -> Dict:
    """Load previous state from file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"repos": [], "releases": {}, "tags": {}}


def save_state(state: Dict) -> None:
    """Save current state to file (atomic-ish)."""
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def get_headers() -> Dict:
    """Get GitHub API headers."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers


def fetch_repos() -> List[Dict]:
    """Fetch all repositories for the organization (paginated)."""
    url = f"{GITHUB_API_BASE}/orgs/{GITHUB_ORG}/repos"
    headers = get_headers()
    repos: List[Dict] = []
    page = 1

    while True:
        resp = requests.get(url, headers=headers, params={"per_page": PER_PAGE, "page": page})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        repos.extend(data)
        page += 1

    return repos


def fetch_releases(repo_name: str) -> List[Dict]:
    """Fetch releases for a specific repository (paginated)."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_ORG}/{repo_name}/releases"
    headers = get_headers()
    releases: List[Dict] = []
    page = 1

    while True:
        resp = requests.get(url, headers=headers, params={"per_page": PER_PAGE, "page": page})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        releases.extend(data)
        page += 1

    return releases


def fetch_tags(repo_name: str) -> List[Dict]:
    """Fetch tags for a specific repository (paginated)."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_ORG}/{repo_name}/tags"
    headers = get_headers()
    tags: List[Dict] = []
    page = 1

    while True:
        resp = requests.get(url, headers=headers, params={"per_page": PER_PAGE, "page": page})
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        tags.extend(data)
        page += 1

    return tags


def fetch_commit(commit_api_url: str) -> Optional[Dict]:
    """Fetch commit details (if available). Returns None on error."""
    if not commit_api_url:
        return None
    try:
        resp = requests.get(commit_api_url, headers=get_headers())
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def send_feishu_post(title: str, blocks: List[List[Dict[str, Any]]]) -> None:
    """
    Send a Feishu 'post' rich message.
    blocks: list of block rows, each block is a list of elements like {"tag": "text", "text": "..."} or {"tag":"a","text":"...","href":"..."}
    """
    if not FEISHU_WEBHOOK_URL:
        print("Warning: FEISHU_WEBHOOK_URL not set, skipping Feishu notification")
        return

    payload = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": blocks
                }
            }
        }
    }

    try:
        resp = requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"Feishu card sent: {title}")
    except Exception as e:
        print(f"Failed to send Feishu card: {e}")


def is_special_release(tag_name: str) -> bool:
    """Check if this is a special release (v3 or r2)."""
    return "v3" in tag_name.lower() or "r2" in tag_name.lower()


def detect_new_repos(current_repos: List[Dict], state: Dict) -> List[Dict]:
    """Detect new repositories by name."""
    known_repo_names = {repo["name"] for repo in state.get("repos", [])}
    new_repos = [repo for repo in current_repos if repo["name"] not in known_repo_names]
    return new_repos


def detect_new_releases(repo_name: str, current_releases: List[Dict], state: Dict) -> List[Dict]:
    """Detect new releases for a repository by release.id."""
    known_releases = state.get("releases", {}).get(repo_name, [])
    known_ids = {r["id"] for r in known_releases}
    new_releases = [r for r in current_releases if r["id"] not in known_ids]
    return new_releases


def detect_new_tags(repo_name: str, current_tags: List[Dict], state: Dict) -> List[Dict]:
    """Detect new tags for a repository by tag.name."""
    known_tags = state.get("tags", {}).get(repo_name, [])
    known_names = {t["name"] for t in known_tags}
    new_tags = [t for t in current_tags if t["name"] not in known_names]
    return new_tags


def format_repo_blocks(repo: Dict) -> (str, List[List[Dict[str, str]]]):
    """Format repository into Feishu post blocks."""
    title = f"🆕 New Repository: {repo['name']}"
    # Build blocks (one row per field)
    blocks: List[List[Dict[str, str]]] = []
    def add_field(label: str, value: str):
        blocks.append([{"tag": "text", "text": f"{label}: {value}"}])

    add_field("Repository", repo.get("full_name", repo["name"]))
    add_field("Description", repo.get("description") or "N/A")
    add_field("URL", repo.get("html_url", "N/A"))
    add_field("Created At", repo.get("created_at", "N/A"))
    add_field("Updated At", repo.get("updated_at", "N/A"))
    add_field("Language", repo.get("language", "N/A"))
    add_field("Stars", str(repo.get("stargazers_count", "N/A")))
    add_field("Watchers", str(repo.get("watchers_count", "N/A")))
    add_field("Forks", str(repo.get("forks_count", "N/A")))
    add_field("Open Issues", str(repo.get("open_issues_count", "N/A")))

    # Add a link block
    blocks.append([{"tag": "a", "text": "Open repository", "href": repo.get("html_url", "")}])

    return title, blocks


def format_release_blocks(release: Dict, repo_name: str) -> (str, List[List[Dict[str, str]]]):
    """Format release into Feishu post blocks."""
    tag_name = release.get("tag_name", "unknown")
    is_special = is_special_release(tag_name)
    title = f"🚀 Special Release - {repo_name} {tag_name} 🚀" if is_special else f"📦 New Release: {repo_name} {tag_name}"

    blocks: List[List[Dict[str, str]]] = []
    def add_field(label: str, value: str):
        blocks.append([{"tag": "text", "text": f"{label}: {value}"}])

    add_field("Repository", f"{GITHUB_ORG}/{repo_name}")
    add_field("Release Name", release.get("name", tag_name))
    add_field("Tag", tag_name)
    add_field("Published At", release.get("published_at", "N/A"))
    add_field("Author", (release.get("author") or {}).get("login", "N/A"))

    if release.get("body"):
        notes = release["body"][:800]
        if len(release["body"]) > 800:
            notes += "..."
        add_field("Release Notes", notes)

    add_field("URL", release.get("html_url", "N/A"))
    blocks.append([{"tag": "a", "text": "View Release", "href": release.get("html_url", "")}])

    return title, blocks


def format_tag_blocks(tag: Dict, repo_name: str) -> (str, List[List[Dict[str, str]]]):
    """Format tag into Feishu post blocks, including commit info if available."""
    tag_name = tag.get("name", "unknown")
    is_special = is_special_release(tag_name)
    title = f"🏷️ Special Tag: {repo_name} {tag_name}" if is_special else f"🏷️ New Tag: {repo_name} {tag_name}"

    blocks: List[List[Dict[str, str]]] = []
    def add_field(label: str, value: str):
        blocks.append([{"tag": "text", "text": f"{label}: {value}"}])

    add_field("Repository", f"{GITHUB_ORG}/{repo_name}")
    add_field("Tag", tag_name)

    commit = tag.get("commit", {})
    sha = commit.get("sha", "")
    add_field("Commit (sha)", sha[:7] if sha else "N/A")
    # Try fetching commit details to include author/message/date
    commit_url = commit.get("url")
    commit_details = fetch_commit(commit_url) if commit_url else None
    if commit_details:
        author_name = (commit_details.get("commit", {}).get("author") or {}).get("name", "N/A")
        commit_date = (commit_details.get("commit", {}).get("author") or {}).get("date", "N/A")
        commit_msg = (commit_details.get("commit", {}).get("message", "") or "")[:500]
        add_field("Commit Author", author_name)
        add_field("Commit Date", commit_date)
        if commit_msg:
            add_field("Commit Message", commit_msg if len(commit_msg) <= 500 else commit_msg[:500] + "...")
        # add web link to commit (if present)
        html_url = commit_details.get("html_url")
        if html_url:
            blocks.append([{"tag": "a", "text": "View Commit", "href": html_url}])
    else:
        # fallback to commit API URL or repo page
        add_field("Commit URL", commit_url or "N/A")

    return title, blocks


def main() -> None:
    """Main monitoring function."""
    print(f"[{datetime.now().isoformat()}] Starting DeepSeek GitHub Monitor...")

    state = load_state()

    try:
        repos = fetch_repos()
    except Exception as e:
        print(f"Failed to fetch repos: {e}")
        return

    print(f"Found {len(repos)} repositories")

    # Detect new repositories
    new_repos = detect_new_repos(repos, state)
    for repo in new_repos:
        title, blocks = format_repo_blocks(repo)
        send_feishu_post(title, blocks)
        print(f"New repo detected: {repo['name']}")

    # Update repos state
    state["repos"] = [{"name": r["name"], "id": r["id"]} for r in repos]

    # For each repo, check releases and tags
    for repo in repos:
        repo_name = repo["name"]
        print(f"Checking {repo_name}...")

        try:
            releases = fetch_releases(repo_name)
            new_releases = detect_new_releases(repo_name, releases, state)

            # Notify new releases
            for release in new_releases:
                title, blocks = format_release_blocks(release, repo_name)
                send_feishu_post(title, blocks)
                print(f"New release detected: {repo_name} {release.get('tag_name')}")

            # Always update state["releases"][repo_name] to the current list (possibly empty)
            state["releases"][repo_name] = [{"id": r["id"], "tag_name": r.get("tag_name", "")} for r in releases]

            # Tags
            tags = fetch_tags(repo_name)
            # Build a set of tag names that correspond to releases already known or newly detected in this run
            release_tag_names_in_state = {r["tag_name"] for r in state.get("releases", {}).get(repo_name, []) if r.get("tag_name")}
            # Include newly found releases in this run (so we don't notify their tags twice)
            release_tag_names_in_run = {r.get("tag_name") for r in new_releases if r.get("tag_name")}
            notified_tag_names = release_tag_names_in_state.union(release_tag_names_in_run)

            # Detect new tags by comparing to state tags (names)
            known_tags = state.get("tags", {}).get(repo_name, [])
            known_tag_names = {t["name"] for t in known_tags}
            new_tags = [t for t in tags if t["name"] not in known_tag_names]

            for tag in new_tags:
                tag_name = tag.get("name")
                if tag_name in notified_tag_names:
                    # Skip tags that are already covered by releases (either in state or new in this run)
                    print(f"Skipping tag {tag_name} for {repo_name} because it matches a release tag")
                    continue
                title, blocks = format_tag_blocks(tag, repo_name)
                send_feishu_post(title, blocks)
                print(f"New tag detected: {repo_name} {tag_name}")

            # Always update state tags (possibly empty)
            state["tags"][repo_name] = [{"name": t["name"], "commit": t.get("commit", {}).get("sha", "")} for t in tags]

        except Exception as e:
            print(f"Error processing {repo_name}: {e}")

    # Save updated state
    save_state(state)
    print(f"[{datetime.now().isoformat()}] Monitor completed")


if __name__ == "__main__":
    main()