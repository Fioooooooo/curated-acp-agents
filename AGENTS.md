# AGENTS.md

Guidance for AI agents working in this repository.

## What this is

A **curated** list of ACP (Agent Client Protocol) agents — not a registry.
Entries must be actively maintained and have real users; they are removed when
they go stale. See [CRITERIA.md](CRITERIA.md) for inclusion/removal policy.

A deeper operational playbook (pitfalls, decision rules, troubleshooting)
lives in [.agents/skills/curate-acp-agent/SKILL.md](.agents/skills/curate-acp-agent/SKILL.md) —
read it before adding or troubleshooting agent entries.

## Layout

- `agents/<id>/agent.json` — entry, **strictly** the official ACP registry
  schema (no custom fields)
- `agents/<id>/curated.yaml` — curation metadata; allowed keys are governed by
  [curated.schema.json](curated.schema.json)
- `agents/<id>/icon.svg` — 16x16 monochrome `currentColor` SVG
- `scripts/build.py` — validate all entries, build `dist/registry.json`, copy
  icons to `dist/icons/` (stdlib only)
- `scripts/check_updates.py` — bump versions from npm/PyPI/GitHub
  Releases/custom sources
- `scripts/health_check.py` — ACP `initialize` handshake smoke test
- `dist/` — published static site (render.com): `index.html`, `registry.json`,
  `icons/`

## Commands

```bash
# Validate entries and rebuild dist/registry.json (run before every commit)
ICON_BASE_URL=https://raw.githubusercontent.com/Fioooooooo/curated-acp-agents/main/agents \
  python3 scripts/build.py

# Check upstream for new versions (rewrites agents/*/agent.json in place)
python3 scripts/check_updates.py

# Smoke-test one agent's ACP handshake
python3 scripts/health_check.py --agent <id>
```

Local downloads may need the user's proxy: `export HTTPS_PROXY=http://127.0.0.1:7890`
(honored by curl, npm, and the Python scripts).

## Conventions

- **No agent-specific special-casing in scripts.** Per-agent behavior must be
  declarative data in `curated.yaml` (`version_source_url` /
  `version_source_pattern`, `health: requires-auth`).
- To add a `curated.yaml` field: extend `curated.schema.json` first, then
  `CURATED_ALLOWED_KEYS` in `scripts/build.py`. Unknown keys fail the build.
- Versions in `agent.json` are semver, optionally with prerelease
  (`2026.8.11-e8db854`); distribution URLs must contain the version (a
  zero-padded variant is accepted).
- Verify the ACP handshake (`health_check.py --agent <id>`) before admitting
  or after changing an entry's distribution.
- README.md's agent table must stay in sync with `agents/`.

## Boundaries

- Do not commit or push unless the user explicitly asks.
- Do not add dependencies to the scripts — Python stdlib only.
- Do not weaken build.py validation to make a bad entry pass; fix the entry.
