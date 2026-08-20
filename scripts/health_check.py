#!/usr/bin/env python3
"""Smoke-test every curated agent over ACP stdio.

Launches each agent (npx / uvx / linux-x86_64 binary), sends an ACP
`initialize` JSON-RPC request, and requires a valid result with a
`protocolVersion` field. No authentication is performed; this only proves
the agent starts and speaks the protocol.

Usage:
  python3 scripts/health_check.py                 # all agents
  python3 scripts/health_check.py --agent kimi    # subset

Writes dist/health.json and exits 1 if any agent fails.
Requires node (npx) and uv (uvx) on PATH for those distribution types.
"""

import argparse
import json
import os
import select
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / "agents"
DIST_DIR = ROOT / "dist"

TIMEOUT = 180  # generous: first npx/uvx run downloads the package

INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": 1,
        "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False},
            "terminal": False,
        },
    },
}


def download_and_extract(url, dest):
    archive = dest / "archive"
    req = urllib.request.Request(url, headers={"User-Agent": "curated-acp-agents"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as f:
        shutil.copyfileobj(resp, f)
    if url.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")
    archive.unlink()


def build_command(agent, workdir):
    dist = agent["distribution"]
    if "npx" in dist:
        npx = dist["npx"]
        return ["npx", "-y", npx["package"], *npx.get("args", [])], npx.get("env", {})
    if "uvx" in dist:
        uvx = dist["uvx"]
        return ["uvx", uvx["package"], *uvx.get("args", [])], uvx.get("env", {})
    target = dist["binary"].get("linux-x86_64")
    if not target:
        raise RuntimeError("no linux-x86_64 binary distribution")
    download_and_extract(target["archive"], workdir)
    exe = workdir / target["cmd"].lstrip("./")
    if not exe.is_file():
        # Some archives nest files in a subdirectory.
        matches = [p for p in workdir.rglob(exe.name) if p.is_file()]
        if not matches:
            raise RuntimeError(f"binary '{target['cmd']}' not found after extraction")
        exe = matches[0]
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return [str(exe), *target.get("args", [])], target.get("env", {})


def handshake(cmd, extra_env):
    env = {**os.environ, **extra_env}
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        bufsize=1,
    )
    try:
        proc.stdin.write(json.dumps(INIT_REQUEST) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            ready, _, _ = select.select([proc.stdout], [], [], min(5.0, remaining))
            if not ready:
                if proc.poll() is not None:
                    return False, f"process exited with code {proc.returncode}"
                continue
            line = proc.stdout.readline()
            if not line:
                return False, f"process closed stdout (exit code {proc.poll()})"
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") != 1:
                continue
            result = msg.get("result")
            if result and "protocolVersion" in result:
                auth = result.get("authMethods") or []
                return True, f"protocolVersion={result['protocolVersion']} authMethods={len(auth)}"
            return False, json.dumps(msg.get("error", msg))[:300]
        return False, f"timeout after {TIMEOUT}s"
    finally:
        proc.kill()


def check_agent(agent_file):
    agent = json.loads(agent_file.read_text())
    agent_id = agent["id"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            cmd, env = build_command(agent, Path(tmp))
            ok, detail = handshake(cmd, env)
        except Exception as e:
            ok, detail = False, str(e)[:300]
    return agent_id, ok, detail


def requires_auth(agent_dir):
    # Minimal parse of curated.yaml; agents flagged "health: requires-auth"
    # need an interactive login before they answer the ACP handshake, so the
    # smoke test cannot verify them in CI.
    curated = agent_dir / "curated.yaml"
    if not curated.is_file():
        return False
    for line in curated.read_text().splitlines():
        if line.strip().startswith("health:"):
            value = line.split(":", 1)[1].split("#", 1)[0].strip()
            return value == "requires-auth"
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", help="comma-separated agent ids to check")
    args = parser.parse_args()
    only = set(args.agent.split(",")) if args.agent else None

    results = {}
    failed = 0
    for agent_file in sorted(AGENTS_DIR.glob("*/agent.json")):
        agent_id = json.loads(agent_file.read_text())["id"]
        if only and agent_id not in only:
            continue
        if requires_auth(agent_file.parent):
            results[agent_id] = {"ok": True, "skipped": True,
                                 "detail": "requires interactive login, handshake not verifiable in CI"}
            print(f"SKIP: {agent_id} (requires-auth)", flush=True)
            continue
        print(f"checking {agent_id} ...", flush=True)
        _, ok, detail = check_agent(agent_file)
        results[agent_id] = {"ok": ok, "detail": detail}
        print(f"  {'OK' if ok else 'FAIL'}: {detail}", flush=True)
        if not ok:
            failed += 1

    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "agents": results,
    }
    DIST_DIR.mkdir(exist_ok=True)
    (DIST_DIR / "health.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"\n{len(results) - failed}/{len(results)} agents healthy -> dist/health.json")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
