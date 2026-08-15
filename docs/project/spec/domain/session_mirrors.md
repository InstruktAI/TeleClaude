---
visibility: internal
description: Frozen v1 ownership anchor for transcript-derived historical session search.
---

# Session Mirrors Domain Spec — Spec

## What it is

The v1 session-mirrors area derives durable searchable history from native
agent transcripts. Mirrors are historical projections; live session control
remains in agent runtime.

The `telec sessions` and `telec history` command families divide by their
subject and by what they do to it. `sessions` acts on live sessions — start,
message, tail, revive, end — and enumerates them so they can be acted on.
`history` finds and reads conversations in the durable archive, which outlives
the sessions recorded in it, and acts on nothing it finds.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/session_mirrors/`.
- **Implementation roots:** `teleclaude/mirrors/` and history API/CLI surfaces.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement session-history design
  belongs to TeleClaudeNext.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
