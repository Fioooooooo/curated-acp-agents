---
name: curate-acp-agent
description: Workflows and hard-won conventions for the curated-acp-agents repo — adding/verifying ACP agent entries, version-source rules, health checks, release process
type: prompt
whenToUse: When adding, updating, removing, or troubleshooting agent entries or automation in the curated-acp-agents repository
---

# Curated ACP Agents — operational knowledge

This repo curates ACP agents (goal: **curate**, not registry). Source of truth:
`agents/<id>/{agent.json, curated.yaml, icon.svg}` → `scripts/build.py` validates
and aggregates into `dist/registry.json` + copies icons to `dist/icons/`.
`agents[]` entries are strictly official ACP registry schema; the envelope adds
a top-level `curation` map (keyed by agent id) with the curated.yaml metadata.
`dist/` is published as a static site (render.com), with `index.html` rendering
cards from registry.json.

## Golden rules

- `agent.json` must stay **strictly compatible with the official registry
  schema** — no custom fields. Curation metadata goes only in `curated.yaml`,
  whose allowed keys are governed by `curated.schema.json` (unknown keys fail
  the build; extend the schema file first, then `CURATED_ALLOWED_KEYS` in
  `scripts/build.py`).
- A binary `sha256`, when present, must be lowercase hex and traceable to an
  upstream integrity value. Follow the official registry workflow: import
  GitHub Release asset `digest` values; for npm tarballs, verify
  `dist.integrity` before deriving SHA-256. If upstream publishes no digest,
  omit the field rather than presenting a self-downloaded hash as proof of
  origin. `build.py` validates present hashes but accepts their absence, as
  allowed by the official schema.
- If an entry diverges from the official registry's entry for the same agent
  (distribution, args, ID, version form), record the how/why in
  `curated.yaml`'s `divergence` field.
- **No agent-specific special-casing in generic scripts.** Anything per-agent
  must be declarative data in `curated.yaml` (e.g. `version_source_url` /
  `version_source_pattern`, `health: requires-auth`).
- Never commit or push unless the user explicitly asks. Before committing,
  always rerun `ICON_BASE_URL=https://raw.githubusercontent.com/Fioooooooo/curated-acp-agents/main/agents python3 scripts/build.py`
  so `dist/registry.json` is in sync.
- Local downloads can be slow; the user's VPN proxy is `http://127.0.0.1:7890`
  — export `HTTPS_PROXY`/`HTTP_PROXY` for curl/npm/python (urllib honors env
  proxies automatically). CI has no proxy.

## Adding an agent

1. Verify upstream health: GitHub API stars/pushed_at/archived; beware moved
   repos (301) and archived ones — the official registry lists several stale
   ones (`zed-industries/codex-acp` is archived; claude-acp/goose/junie moved).
2. Choose distribution: `npx`/`uvx` (pinned `pkg@version`) preferred; `binary`
   with version in the archive URL otherwise. Include `sha256` only when it
   comes from an upstream GitHub Release asset digest or from a download
   verified against npm `dist.integrity`. Icon: 16x16 monochrome
   `currentColor` SVG (fetch from the official CDN when the agent is listed
   there: `https://cdn.agentclientprotocol.com/registry/v1/latest/<id>.svg`).
3. Verify the ACP handshake **before** admitting:
   `python3 scripts/health_check.py --agent <id>` (npx/uvx/linux-binary only;
   on macOS, verify darwin binaries manually by downloading, extracting, and
   piping an `initialize` JSON-RPC request to the process).
4. Fill `curated.yaml` (tier/status/added/reason, plus optional fields per
   schema), run build.py, update the README table.

## Version detection (scripts/check_updates.py)

Precedence: explicit `version_source_*` in curated.yaml → npx (npm latest) →
uvx (PyPI latest) → binary (GitHub Releases of `repository`). Versions are
normalized (leading zeros stripped: `2026.08.11` → `2026.8.11`); rewrites
replace both forms in agent.json. Date-hash versions like cursor's
`2026.8.11-e8db854` are valid semver-with-prerelease entries.

Use `version_source_url` + `version_source_pattern` (regex, first capture
group = version) when:
- the vendor has no public repo (cursor: parse `https://cursor.com/install`),
- the repo's GitHub Releases do **not** track the CLI (cline: repo releases
  are `desktop-v*`; poll `https://registry.npmjs.org/cline/latest` with
  pattern `"version":"([0-9.]+)"` instead).

## Known pitfalls (discovered the hard way)

- **`npx <pkg>` exit 127 / "command not found"** usually means the package's
  bin never got linked — check for bin-name conflicts between the meta package
  and its platform packages (cline is broken this way: `cline` and
  `@cline/cli-*` both declare bin `cline`). Workaround: binary distribution
  pointing at the npm platform tarballs
  (`https://registry.npmjs.org/@<scope>/<pkg>/-/<pkg>-<version>.tgz`, binary
  inside at `package/bin/<name>`; `.tgz` is a supported archive format).
- **timeout ≠ auth required.** First-run npx downloads count into the 180s
  handshake timeout. To diagnose, run the command manually with stderr shown
  before concluding anything about login requirements. qoder, codebuddy-code,
  cursor, cline all answer `initialize` **without** login — none should carry
  `health: requires-auth`.
- Binary archives may nest the executable (`dist-package/cursor-agent`,
  `package/bin/cline`) — `cmd` must include the full relative path.
- Some npm packages (qoder, codebuddy) rely on `postinstall` downloads; a
  killed/slow install leaves a broken tree (`enoent` on reinstall — wipe
  `node_modules` first).
- `@github/copilot`'s bin is an `npm-loader.js` that `import.meta.resolve`s
  the platform package and spawns the native binary inside. A first `npx`
  run can fail with `TAR_ENTRY_ERROR ENOENT` / `sh: copilot: command not
  found`; simply re-running npx repairs the tree (no manual wipe needed).

## Automation

- `update.yml`: twice daily (cron `41 3,15 * * *`); bumps agent.json, rebuilds
  registry.json, auto-commits to main as github-actions[bot]; per-agent check
  failures open a deduped `update-check` issue (comment if one is open).
- `health.yml`: weekly Monday; ACP handshake for all agents; failures open a
  deduped `health` issue. Repeated failures feed the stale→removal process in
  CRITERIA.md.
- `validate.yml`: PR/push validation. `ICON_BASE_URL` in workflows reads the
  `ICON_BASE_URL` **repository variable** (Settings → Secrets and variables →
  Actions → Variables), defaulting to raw.githubusercontent.com; set it to the
  CDN URL (`https://<app>.onrender.com/icons`) after deploy.
- No `gh` CLI on the user's machine: read Actions state via the unauthenticated
  REST API (`/actions/runs`, `/actions/jobs`); job **log download requires a
  token**, so ask the user to paste failing step output instead.

## Removal

Follow CRITERIA.md: stale (no upstream activity ~6 months / archived repo /
repeated health failures) → 30 days → delete `agents/<id>/` via PR.
