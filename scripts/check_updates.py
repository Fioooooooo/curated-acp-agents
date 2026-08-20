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

After a binary distribution is bumped, checksums are refreshed from an
upstream integrity source when one is available:
  - GitHub Release asset digests for GitHub-hosted release archives
  - npm's dist.integrity for registry.npmjs.org tarballs (the tarball is
    downloaded, verified against that SHA-512 SRI value, then SHA-256 is
    recorded for the ACP manifest)

If no upstream integrity source exists, any checksum for the old URL is
removed and a warning is emitted.  A checksum of bytes we merely downloaded
would pin those bytes, but would not establish their upstream authenticity.

Version strings embedded in package specs and archive URLs are rewritten
in place, which assumes upstream keeps a stable URL pattern across
releases (true for all currently curated agents; re-verify on failure).

Usage: python3 scripts/check_updates.py
Prints one line per bumped agent. Exits 0 whether or not updates were found.
Stdlib only; set GITHUB_TOKEN to raise the GitHub API rate limit.
HTTP(S)_PROXY environment variables are honored for all requests.
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import urllib.parse
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


def github_release_digests(repo_url, version):
    """Return GitHub's SHA-256 digests keyed by release asset filename."""
    m = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url or "")
    if not m:
        return {}
    owner, repo = m.group(1), m.group(2).removesuffix(".git")
    for tag in (f"v{version}", version):
        try:
            release = http_json(
                f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
            )
        except Exception:
            continue
        digests = {}
        for asset in release.get("assets", []):
            digest = asset.get("digest", "")
            if asset.get("name") and digest.startswith("sha256:"):
                digests[asset["name"]] = digest.removeprefix("sha256:").lower()
        return digests
    return {}


def npm_package_from_tarball(url):
    """Extract an npm package name from its canonical registry tarball URL."""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname != "registry.npmjs.org":
        return None
    parts = urllib.parse.unquote(parsed.path).strip("/").split("/")
    try:
        separator = parts.index("-")
    except ValueError:
        return None
    package_parts = parts[:separator]
    if len(package_parts) == 1:
        return package_parts[0]
    if len(package_parts) == 2 and package_parts[0].startswith("@"):
        return "/".join(package_parts)
    return None


def sha256_verified_by_npm_integrity(url, version):
    """Verify an npm tarball against dist.integrity and return its SHA-256."""
    package = npm_package_from_tarball(url)
    if not package:
        return None
    encoded_package = urllib.parse.quote(package, safe="")
    metadata = http_json(f"https://registry.npmjs.org/{encoded_package}/{version}")
    dist = metadata.get("dist", {})
    if dist.get("tarball") != url:
        raise ValueError(f"npm metadata tarball URL mismatch for {package}@{version}")
    integrity = dist.get("integrity", "")
    algorithm, separator, encoded_digest = integrity.partition("-")
    if separator != "-" or algorithm not in hashlib.algorithms_available:
        raise ValueError(f"unsupported npm integrity for {package}@{version}: {integrity!r}")
    try:
        expected_digest = base64.b64decode(encoded_digest, validate=True)
    except ValueError as e:
        raise ValueError(f"invalid npm integrity for {package}@{version}") from e

    upstream_hasher = hashlib.new(algorithm)
    sha256_hasher = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "curated-acp-agents"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        while chunk := resp.read(1 << 20):
            upstream_hasher.update(chunk)
            sha256_hasher.update(chunk)
    if not hmac.compare_digest(upstream_hasher.digest(), expected_digest):
        raise ValueError(f"npm integrity mismatch for {package}@{version}")
    return sha256_hasher.hexdigest()


def refresh_binary_checksums(agent, version, remove_unverifiable=False):
    """Refresh checksums only when backed by an upstream integrity value."""
    binary = agent.get("distribution", {}).get("binary", {})
    repository = agent.get("repository", "")
    release_digests = None
    for platform, target in sorted(binary.items()):
        archive = target["archive"]
        digest = sha256_verified_by_npm_integrity(archive, version)
        source = "npm dist.integrity"
        if digest is None and "github.com/" in archive and "/releases/download/" in archive:
            if release_digests is None:
                release_digests = github_release_digests(repository, version)
            digest = release_digests.get(archive.rsplit("/", 1)[-1])
            source = "GitHub release digest"
        if digest:
            target["sha256"] = digest
            print(f"  sha256 {agent['id']}/{platform} ({source}): {digest[:16]}…")
        else:
            if remove_unverifiable:
                target.pop("sha256", None)
            checksum_state = (
                "omitted" if "sha256" not in target else "existing value preserved"
            )
            print(
                f"WARN: {agent['id']}/{platform}: no upstream checksum; "
                f"sha256 {checksum_state}",
                file=sys.stderr,
            )


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
    parser = argparse.ArgumentParser(description="Update curated ACP agent versions")
    parser.add_argument(
        "--refresh-checksums",
        action="store_true",
        help="refresh checksums for existing binary versions from upstream integrity values",
    )
    args = parser.parse_args()

    updated = []
    checksum_updated = []
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
            if args.refresh_checksums and "binary" in agent.get("distribution", {}):
                before = json.dumps(agent, sort_keys=True)
                refresh_binary_checksums(agent, old)
                if json.dumps(agent, sort_keys=True) != before:
                    agent_file.write_text(json.dumps(agent, indent=2, ensure_ascii=False) + "\n")
                    checksum_updated.append(agent_id)
                    print(f"CHECKSUMS: {agent_id} {old}")
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
        bumped = json.loads(text)
        if "binary" in bumped.get("distribution", {}):
            # Never carry an old URL's hash forward.  Refresh only from an
            # upstream-published integrity value; otherwise omit and warn.
            refresh_binary_checksums(bumped, new, remove_unverifiable=True)
            text = json.dumps(bumped, indent=2, ensure_ascii=False) + "\n"
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

    print(
        f"\n{len(updated)} agent(s) updated, "
        f"{len(checksum_updated)} checksum set(s) refreshed, "
        f"{len(failures)} failure(s)",
        file=sys.stderr,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
