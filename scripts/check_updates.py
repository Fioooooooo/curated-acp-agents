#!/usr/bin/env python3
"""Check upstream sources for new agent versions and bump agents/*/agent.json.

Sources:
  - npx    -> npm registry latest version
  - uvx    -> PyPI latest version
  - binary -> GitHub Releases latest tag of the agent's repository

Version strings embedded in package specs and archive URLs are rewritten
in place, which assumes upstream keeps a stable URL pattern across
releases (true for all currently curated agents; re-verify on failure).

Usage: python3 scripts/check_updates.py
Prints one line per bumped agent. Exits 0 whether or not updates were found.
Stdlib only; set GITHUB_TOKEN to raise the GitHub API rate limit.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"


def http_json(url):
    headers = {"User-Agent": "curated-acp-agents"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def npm_latest(package):
    return http_json(f"https://registry.npmjs.org/{package.replace('/', '%2f')}/latest")["version"]


def pypi_latest(package):
    return http_json(f"https://pypi.org/pypi/{package}/json")["info"]["version"]


def github_latest_version(repo_url):
    m = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url or "")
    if not m:
        return None
    tag = http_json(f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/releases/latest").get("tag_name", "")
    return tag.lstrip("v") or None


def package_name(spec):
    # "@scope/pkg@1.2.3" -> "@scope/pkg"; "pkg@1.2.3" -> "pkg"; "pkg" -> "pkg"
    if spec.startswith("@"):
        parts = spec.split("@")
        return "@" + parts[1]
    return spec.split("@")[0]


def latest_version_for(agent):
    dist = agent.get("distribution", {})
    if "npx" in dist:
        return npm_latest(package_name(dist["npx"]["package"]))
    if "uvx" in dist:
        return pypi_latest(package_name(dist["uvx"]["package"]))
    if "binary" in dist:
        return github_latest_version(agent.get("repository"))
    return None


def main():
    updated = []
    for agent_file in sorted(AGENTS_DIR.glob("*/agent.json")):
        agent = json.loads(agent_file.read_text())
        agent_id = agent["id"]
        old = agent["version"]
        try:
            new = latest_version_for(agent)
        except Exception as e:
            print(f"WARN: {agent_id}: update check failed: {e}", file=sys.stderr)
            continue
        if not new:
            print(f"WARN: {agent_id}: no upstream version found", file=sys.stderr)
            continue
        if new == old:
            print(f"up-to-date: {agent_id} {old}")
            continue
        # Rewrites the version field plus every pinned package spec and
        # versioned archive URL (including "v<old>" tag prefixes).
        text = agent_file.read_text()
        if old not in text:
            print(f"WARN: {agent_id}: version string not found in file, skipping", file=sys.stderr)
            continue
        agent_file.write_text(text.replace(old, new))
        updated.append((agent_id, old, new))
        print(f"UPDATED: {agent_id} {old} -> {new}")

    print(f"\n{len(updated)} agent(s) updated", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
