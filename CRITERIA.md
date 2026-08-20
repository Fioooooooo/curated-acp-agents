# Curation Criteria

This repository is a **curated** list of ACP agents, not a registry. Entries
are included because they are actively maintained and have real users — and
removed when that stops being true.

## Inclusion criteria

An agent must meet all of the following:

1. **Works over ACP**: passes the automated `initialize` handshake smoke test
   (`scripts/health_check.py`).
2. **Actively maintained**: commits or releases within the last ~3 months.
3. **Real users or credible backing**: an established vendor/org (Anthropic,
   OpenAI, Google, etc.) or a community project with meaningful adoption
   (rule of thumb: ≥1k GitHub stars).
4. **Pinned, verifiable distribution**: at least one of `npx`, `uvx`, or
   `binary`, with versions pinned (no `@latest`, no `/latest/` URLs) and a
   public source repository we can monitor.
5. **License allows redistribution** of the package/archive as referenced.

## Adding an agent

1. Open an issue or PR proposing the agent with a filled `agents/<id>/agent.json`
   and a 16x16 monochrome `icon.svg` (same rules as the upstream registry).
2. CI validates the entry (`scripts/build.py`).
3. A maintainer runs the health check (`scripts/health_check.py --agent <id>`)
   and reviews the entry against the criteria above.
4. On merge, the agent enters daily version tracking and weekly health checks.

## Stale and removal policy

Curation only has value if dead entries leave. The process is two-stage:

**Marked `stale`** (in `agents/<id>/curated.yaml`) when any of:

- no upstream commit or release for ~6 months,
- the source repository is archived, moved, or deleted,
- the weekly health check fails repeatedly (rule of thumb: 2+ consecutive runs).

A stale entry stays in `registry.json` but the maintainer team investigates.

**Removed** when any of:

- `stale` for 30 days without recovery,
- upstream deletes the repository or distribution package,
- the license changes to disallow redistribution,
- the project officially deprecates its ACP support.

Removal is a plain PR deleting `agents/<id>/`. Git history keeps the record.

## Version updates

Versions are bumped automatically by `scripts/check_updates.py` (daily, via
the `update.yml` workflow) from npm, PyPI, or GitHub Releases. Bumps land as
pull requests for human review — automation proposes, curation disposes.
