#!/usr/bin/env python3
"""Validate agents/*/agent.json entries and build dist/registry.json.

The output format is identical to the official ACP registry
(https://github.com/agentclientprotocol/registry), so ACP clients can
consume it as a drop-in replacement.

Usage: python3 scripts/build.py
Stdlib only, no dependencies.
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
DIST_DIR = ROOT / "dist"

# Base URL used for the "icon" field of each entry in registry.json.
ICON_BASE_URL = os.environ.get(
    "ICON_BASE_URL",
    "https://raw.githubusercontent.com/OWNER/curated-acp-agents/main/agents",
)

PLATFORMS = {
    "darwin-aarch64",
    "darwin-x86_64",
    "linux-aarch64",
    "linux-x86_64",
    "windows-aarch64",
    "windows-x86_64",
}
ARCHIVE_EXTS = (".zip", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2")
ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def fail(errors, msg):
    errors.append(msg)


def validate_agent(agent, agent_dir, errors):
    ctx = agent.get("id", agent_dir.name)

    for field in ("id", "name", "version", "description", "distribution"):
        if field not in agent:
            fail(errors, f"{ctx}: missing required field '{field}'")

    agent_id = agent.get("id", "")
    if not ID_RE.match(agent_id):
        fail(errors, f"{ctx}: id must match {ID_RE.pattern}")
    if agent_id != agent_dir.name:
        fail(errors, f"{ctx}: id must match directory name '{agent_dir.name}'")

    version = agent.get("version", "")
    if not SEMVER_RE.match(version):
        fail(errors, f"{ctx}: version '{version}' is not semver (x.y.z)")

    dist = agent.get("distribution", {})
    if not any(k in dist for k in ("binary", "npx", "uvx")):
        fail(errors, f"{ctx}: distribution needs at least one of binary/npx/uvx")

    for key in ("npx", "uvx"):
        if key in dist:
            spec = dist[key].get("package", "")
            if not spec:
                fail(errors, f"{ctx}: distribution.{key}.package is required")
            elif spec.endswith("@latest"):
                fail(errors, f"{ctx}: {key} package must not use @latest")
            elif "@" + version not in spec and "==" + version not in spec:
                fail(errors, f"{ctx}: {key} package '{spec}' not pinned to version {version}")

    if "binary" in dist:
        for platform, target in dist["binary"].items():
            if platform not in PLATFORMS:
                fail(errors, f"{ctx}: unknown platform '{platform}'")
                continue
            archive = target.get("archive", "")
            if not archive:
                fail(errors, f"{ctx}: binary.{platform}.archive is required")
                continue
            if not target.get("cmd"):
                fail(errors, f"{ctx}: binary.{platform}.cmd is required")
            if "/latest/" in archive:
                fail(errors, f"{ctx}: binary.{platform} URL must not contain /latest/")
            base = archive.split("?")[0]
            if not base.endswith(ARCHIVE_EXTS) and "." in base.rsplit("/", 1)[-1]:
                fail(errors, f"{ctx}: binary.{platform} unsupported archive format: {archive}")
            if version not in archive:
                fail(errors, f"{ctx}: binary.{platform} URL does not contain version {version}")

    if not (agent_dir / "icon.svg").is_file():
        fail(errors, f"{ctx}: missing icon.svg")


def main():
    errors = []
    agents = []

    for agent_dir in sorted(AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_file = agent_dir / "agent.json"
        if not agent_file.is_file():
            fail(errors, f"{agent_dir.name}: missing agent.json")
            continue
        try:
            agent = json.loads(agent_file.read_text())
        except json.JSONDecodeError as e:
            fail(errors, f"{agent_dir.name}: invalid JSON: {e}")
            continue
        validate_agent(agent, agent_dir, errors)
        agent["icon"] = f"{ICON_BASE_URL}/{agent['id']}.svg"
        agents.append(agent)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    agents.sort(key=lambda a: a["id"])
    registry = {"version": "1.0.0", "agents": agents}

    DIST_DIR.mkdir(exist_ok=True)
    out = DIST_DIR / "registry.json"
    out.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")
    print(f"OK: {len(agents)} agents -> {out}")


if __name__ == "__main__":
    main()
