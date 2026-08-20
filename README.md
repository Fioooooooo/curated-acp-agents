# Curated ACP Agents

A curated list of [Agent Client Protocol](https://agentclientprotocol.com)
agents — actively maintained, health-checked, and safe to recommend. Unlike
the [official registry](https://github.com/agentclientprotocol/registry),
this list is opinionated: entries must have an active upstream and real
users, and are removed when they go stale. See [CRITERIA.md](CRITERIA.md).

## Registry JSON

`dist/registry.json` follows the
[official registry format](https://github.com/agentclientprotocol/registry/blob/main/FORMAT.md)
for every entry in `agents[]`, so ACP clients can consume it as a drop-in
source when they tolerate unknown top-level fields. The envelope adds one
extension: a top-level `curation` object keyed by agent id carrying the
curation metadata (`tier`, `status`, `added`, `reason`, and optional `health`
/ `divergence`) — clients that don't care can ignore it. This is an
opinionated subset, not a complete or semantically transparent replacement
for the official registry.

```
https://raw.githubusercontent.com/Fioooooooo/curated-acp-agents/main/dist/registry.json
```

## Curated agents

| Agent | Distribution | Notes |
|---|---|---|
| [Claude Agent](https://github.com/agentclientprotocol/claude-agent-acp) | npx | Official Anthropic adapter |
| [Codex CLI](https://github.com/agentclientprotocol/codex-acp) | npx | Official OpenAI adapter |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | npx | `--acp` |
| [Kimi Code CLI](https://github.com/MoonshotAI/kimi-code) | npx | `kimi acp`; successor to the Python Kimi CLI (listed as `kimi` in the official registry — a different, older product) |
| [Cursor CLI](https://cursor.com/cli) | binary | `agent acp`; version tracked via cursor.com/install |
| [OpenCode](https://github.com/anomalyco/opencode) | binary | `opencode acp` |
| [goose](https://github.com/aaif-goose/goose) | binary | `goose acp` |
| [Qwen Code](https://github.com/QwenLM/qwen-code) | npx | `--acp` |
| [Cline](https://github.com/cline/cline) | binary | `--acp`; binary via `@cline/cli-*` npm tarballs (npx bin broken upstream) |
| [GitHub Copilot](https://github.com/github/copilot-cli) | npx | `--acp`; same ID and package as the official registry's `github-copilot-cli` |
| [Mistral Vibe](https://github.com/mistralai/mistral-vibe) | binary | dedicated `vibe-acp` binaries |
| [CodeBuddy Code](https://www.codebuddy.cn/cli/) | npx | `--acp`; Tencent Cloud, proprietary |
| Qoder CLI | npx | `--acp`; Qoder AI, proprietary, no public repo |

## How it works

- `agents/<id>/agent.json` — the entry, same schema as the official registry
- `agents/<id>/curated.yaml` — curation metadata (tier, status, reason,
  optional `divergence` explaining how an entry differs from the official
  registry's); embedded into `registry.json` as a top-level `curation` map
- `scripts/build.py` — validates all entries and any upstream-backed binary
  `sha256`, then builds `dist/registry.json`
- `scripts/check_updates.py` — bumps versions from npm / PyPI / GitHub
  Releases; imports GitHub Release asset digests or verifies npm
  `dist.integrity` before deriving a binary `sha256` (runs twice a day,
  auto-commits to `main` with a rebuilt `registry.json`)
- `scripts/health_check.py` — ACP `initialize` handshake smoke test for every
  agent (runs weekly on ubuntu-latest, opens an issue on failure)

## Contributing

Nominate an agent by opening an issue or PR with a new `agents/<id>/`
directory. Entries are reviewed against [CRITERIA.md](CRITERIA.md).

## License

Apache-2.0. Individual agents are subject to their own licenses.
