#!/usr/bin/env python3
"""
DeepSeek GitHub Monitor
Monitors deepseek-ai organization for new repositories, releases, and tags.
Sends notifications to Feishu bot when changes are detected.
"""

import os
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional


GITHUB_ORG = "deepseek-ai"
GITHUB_API_BASE = "https://api.github.com"
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL")
STATE_FILE = "/tmp/deepseek_monitor_state.json"


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
    """Save current state to file."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


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
    """Fetch all repositories for the organization."""
    url = f"{GITHUB_API_BASE}/orgs/{GITHUB_ORG}/repos"
    headers = get_headers()
    repos = []
    page = 1

    while True:
        response = requests.get(url, headers=headers, params={"per_page": 100, "page": page})
        response.raise_for_status()
        data = response.json()
        if not data:
            break
        repos.extend(data)
        page += 1

    return repos


def fetch_releases(repo_name: str) -> List[Dict]:
    """Fetch releases for a specific repository."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_ORG}/{repo_name}/releases"
    headers = get_headers()
    response = requests.get(url, headers=headers, params={"per_page": 100})
    response.raise_for_status()
    return response.json()


def fetch_tags(repo_name: str) -> List[Dict]:
    """Fetch tags for a specific repository."""
    url = f"{GITHUB_API_BASE}/repos/{GITHUB_ORG}/{repo_name}/tags"
    headers = get_headers()
    response = requests.get(url, headers=headers, params={"per_page": 100})
    response.raise_for_status()
    return response.json()


def send_feishu_notification(title: str, content: str) -> None:
    """Send notification to Feishu bot."""
    if not FEISHU_WEBHOOK_URL:
        print("Warning: FEISHU_WEBHOOK_URL not set, skipping notification")
        return

    data = {
        "msg_type": "text",
        "content": {
            "text": f"{title}\n\n{content}"
        }
    }

    response = requests.post(FEISHU_WEBHOOK_URL, json=data)
    response.raise_for_status()
    print(f"Notification sent: {title}")


def is_special_release(tag_name: str) -> bool:
    """Check if this is a special release (v3 or r2)."""
    return "v3" in tag_name.lower() or "r2" in tag_name.lower()


def detect_new_repos(current_repos: List[Dict], state: Dict) -> List[Dict]:
    """Detect new repositories."""
    known_repo_names = {repo["name"] for repo in state["repos"]}
    new_repos = [repo for repo in current_repos if repo["name"] not in known_repo_names]
    return new_repos


def detect_new_releases(repo_name: str, current_releases: List[Dict], state: Dict) -> List[Dict]:
    """Detect new releases for a repository."""
    known_releases = state["releases"].get(repo_name, [])
    known_ids = {r["id"] for r in known_releases}
    new_releases = [r for r in current_releases if r["id"] not in known_ids]
    return new_releases


def detect_new_tags(repo_name: str, current_tags: List[Dict], state: Dict) -> List[Dict]:
    """Detect new tags for a repository."""
    known_tags = state["tags"].get(repo_name, [])
    known_names = {t["name"] for t in known_tags}
    new_tags = [t for t in current_tags if t["name"] not in known_names]
    return new_tags


def format_new_repo(repo: Dict) -> tuple:
    """Format new repository notification."""
    title = f"🆕 New Repository: {repo['name']}"
    content = (
        f"Repository: {repo['full_name']}\n"
        f"Description: {repo.get('description', 'N/A')}\n"
        f"URL: {repo['html_url']}\n"
        f"Created: {repo['created_at']}\n"
        f"Language: {repo.get('language', 'N/A')}"
    )
    return title, content


def format_new_release(release: Dict, repo_name: str) -> tuple:
    """Format new release notification."""
    tag_name = release.get("tag_name", "unknown")
    is_special = is_special_release(tag_name)

    if is_special:
        title = f"🚀 Special Release Alert - {tag_name} 🚀"
    else:
        title = f"📦 New Release: {repo_name} {tag_name}"

    content = (
        f"Repository: {GITHUB_ORG}/{repo_name}\n"
        f"Release: {release.get('name', tag_name)}\n"
        f"Tag: {tag_name}\n"
        f"URL: {release['html_url']}\n"
        f"Published: {release.get('published_at', 'N/A')}\n"
    )

    if release.get("body"):
        # Truncate release notes if too long
        notes = release["body"][:500]
        if len(release["body"]) > 500:
            notes += "..."
        content += f"\nRelease Notes:\n{notes}"

    return title, content


def format_new_tag(tag: Dict, repo_name: str) -> tuple:
    """Format new tag notification."""
    title = f"🏷️ New Tag: {repo_name} {tag['name']}"
    is_special = is_special_release(tag["name"])
    if is_special:
        title = f"🏷️ Special Tag: {tag['name']}"

    content = (
        f"Repository: {GITHUB_ORG}/{repo_name}\n"
        f"Tag: {tag['name']}\n"
        f"Commit: {tag['commit']['sha'][:7]}\n"
        f"URL: {tag['commit']['url']}\n"
    )
    return title, content


def main() -> None:
    """Main monitoring function."""
    print(f"[{datetime.now().isoformat()}] Starting DeepSeek GitHub Monitor...")

    # Load previous state
    state = load_state()

    # Fetch current data
    repos = fetch_repos()
    print(f"Found {len(repos)} repositories")

    # Check for new repositories
    new_repos = detect_new_repos(repos, state)
    for repo in new_repos:
        title, content = format_new_repo(repo)
        send_feishu_notification(title, content)
        print(f"New repo detected: {repo['name']}")

    # Update state repos
    state["repos"] = [{"name": r["name"], "id": r["id"]} for r in repos]

    # Check each repository for new releases and tags
    for repo in repos:
        repo_name = repo["name"]
        print(f"Checking {repo_name}...")

        try:
            # Check releases
            releases = fetch_releases(repo_name)
            new_releases = detect_new_releases(repo_name, releases, state)

            for release in new_releases:
                title, content = format_new_release(release, repo_name)
                send_feishu_notification(title, content)
                print(f"New release detected: {repo_name} {release['tag_name']}")

            # Update state releases
            if releases:
                state["releases"][repo_name] = [{"id": r["id"], "tag_name": r["tag_name"]} for r in releases]

            # Check tags
            tags = fetch_tags(repo_name)
            new_tags = detect_new_tags(repo_name, tags, state)

            for tag in new_tags:
                # Skip if we already notified for this tag via release
                if not any(rt["tag_name"] == tag["name"] for rt in state["releases"].get(repo_name, [])):
                    title, content = format_new_tag(tag, repo_name)
                    send_feishu_notification(title, content)
                    print(f"New tag detected: {repo_name} {tag['name']}")

            # Update state tags
            if tags:
                state["tags"][repo_name] = [{"name": t["name"], "commit": t["commit"]["sha"]} for t in tags]

        except Exception as e:
            print(f"Error processing {repo_name}: {e}")

    # Save updated state
    save_state(state)

    print(f"[{datetime.now().isoformat()}] Monitor completed")


if __name__ == "__main__":
    main()
