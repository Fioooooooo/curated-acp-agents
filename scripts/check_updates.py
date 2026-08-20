#!/usr/bin/env python3
"""Check upstream sources for new agent versions and bump agents/*/agent.json.

Sources, in priority order:
  - custom source declared in curated.yaml as flat keys (always wins):
        version_source_url: https://example.com/install
        version_source_pattern: "download/v?([0-9][0-9a-f.-]*)/"
      (first regex capture group is the version; use when the repo's
      releases don't track the CLI or no public repo exists)
  - npx    -> npm registry latest version
  - uvx    -> PyPI latest version
  - binary -> GitHub Releases latest tag of the agent's repository

All upstream versions are normalized before comparison (leading zeros in
numeric parts are stripped, so a vendor's "2026.08.11" matches a stored
"2026.8.11"). When rewriting agent.json, both the stored form and its
zero-padded variant are replaced, so versioned URLs keep working.

Version strings embedded in package specs and archive URLs are rewritten
in place, which assumes upstream keeps a stable URL pattern across
releases (true for all currently curated agents; re-verify on failure).

Usage: python3 scripts/check_updates.py
Prints one line per bumped agent. Exits 0 whether or not updates were found.
Stdlib only; set GITHUB_TOKEN to raise the GitHub API rate limit.
HTTP(S)_PROXY environment variables are honored for all requests.
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"


def http_get(url):
    headers = {"User-Agent": "curated-acp-agents"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def http_json(url):
    return json.loads(http_get(url))


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


def curated_values(agent_dir):
    # Minimal flat "key: value" reader for curated.yaml.
    values = {}
    curated = agent_dir / "curated.yaml"
    if curated.is_file():
        for line in curated.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, _, value = line.partition(":")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def custom_source_version(agent_dir):
    values = curated_values(agent_dir)
    url, pattern = values.get("version_source_url"), values.get("version_source_pattern")
    if not url or not pattern:
        return None
    m = re.search(pattern, http_get(url).decode("utf-8", "replace"))
    return m.group(1) if m else None


def normalize_version(v):
    # Strip leading zeros from numeric parts: "2026.08.11-x" -> "2026.8.11-x".
    parts = []
    for part in v.split("."):
        num, sep, rest = part.partition("-")
        if num.isdigit():
            part = str(int(num)) + (sep + rest if sep else "")
        parts.append(part)
    return ".".join(parts)


def pad_version(v):
    # Inverse of normalize_version: "2026.8.11-x" -> "2026.08.11-x".
    parts = []
    for part in v.split("."):
        num, sep, rest = part.partition("-")
        if num.isdigit():
            part = num.zfill(2) + (sep + rest if sep else "")
        parts.append(part)
    return ".".join(parts)


def package_name(spec):
    # "@scope/pkg@1.2.3" -> "@scope/pkg"; "pkg@1.2.3" -> "pkg"; "pkg" -> "pkg"
    if spec.startswith("@"):
        parts = spec.split("@")
        return "@" + parts[1]
    return spec.split("@")[0]


def latest_version_for(agent, agent_dir):
    # An explicitly declared version source in curated.yaml always wins over
    # inferred ones (e.g. when the repo's releases don't track the CLI's
    # versions, or the vendor has no public repo at all).
    custom = custom_source_version(agent_dir)
    if custom is not None:
        return normalize_version(custom)
    dist = agent.get("distribution", {})
    if "npx" in dist:
        return npm_latest(package_name(dist["npx"]["package"]))
    if "uvx" in dist:
        return pypi_latest(package_name(dist["uvx"]["package"]))
    if "binary" in dist:
        version = github_latest_version(agent.get("repository"))
        return normalize_version(version) if version else None
    return None


def main():
    updated = []
    failures = []
    for agent_file in sorted(AGENTS_DIR.glob("*/agent.json")):
        agent = json.loads(agent_file.read_text())
        agent_id = agent["id"]
        old = agent["version"]
        try:
            new = latest_version_for(agent, agent_file.parent)
        except Exception as e:
            print(f"WARN: {agent_id}: update check failed: {e}", file=sys.stderr)
            failures.append({"agent": agent_id, "error": str(e)[:300]})
            continue
        if not new:
            print(f"WARN: {agent_id}: no upstream version found", file=sys.stderr)
            failures.append({"agent": agent_id, "error": "no upstream version found"})
            continue
        if new == old:
            print(f"up-to-date: {agent_id} {old}")
            continue
        # Rewrites the version field plus every pinned package spec and
        # versioned archive URL (including "v<old>" tag prefixes and
        # zero-padded date versions embedded in URLs).
        text = agent_file.read_text()
        pairs = {(old, new), (pad_version(old), pad_version(new))}
        if not any(src in text for src, _ in pairs):
            print(f"WARN: {agent_id}: version string not found in file, skipping", file=sys.stderr)
            failures.append({"agent": agent_id, "error": "version string not found in agent.json"})
            continue
        for src, dst in pairs:
            if src != dst:
                text = text.replace(src, dst)
        agent_file.write_text(text)
        updated.append((agent_id, old, new))
        print(f"UPDATED: {agent_id} {old} -> {new}")

    # Failure report consumed by the update workflow to open an issue.
    # One agent's failure never affects the others; the run still succeeds.
    report_path = Path(os.environ.get("UPDATE_FAILURES_FILE", ROOT / "dist" / "update-failures.md"))
    if failures:
        lines = ["## Version update check failures", ""]
        lines += [f"- **{f['agent']}**: {f['error']}" for f in failures]
        report_path.parent.mkdir(exist_ok=True)
        report_path.write_text("\n".join(lines) + "\n")
    elif report_path.exists():
        report_path.unlink()

    print(f"\n{len(updated)} agent(s) updated, {len(failures)} failure(s)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
