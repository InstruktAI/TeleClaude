---
visibility: internal
description: Frozen v1 ownership anchor for transcript-derived historical session search.
---

# Session Mirrors Domain Spec — Spec

## What it is

The v1 session-mirrors area derives durable searchable history from native
agent transcripts. Mirrors are historical projections; live session control
remains in agent runtime.

The `telec sessions` and `telec history` command families divide by whether the
caller can name what they are after. `sessions` acts on a session the caller can
name — start it, message it, tail it, revive it, end it — and its subject is a
session that exists to be acted on. `history` finds and reads conversations the
caller cannot name, addressing an archive that outlives the sessions in it. This
is the division the surface is held to: a verb that answers "which conversation
was that?" belongs to `history`, and a verb that answers "do this to that
session" belongs to `sessions`. A browsing verb belongs to neither, because
browsing names nothing and finds nothing.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/session_mirrors/`.
- **Implementation roots:** `teleclaude/mirrors/` and history API/CLI surfaces.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement session-history design
  belongs to TeleClaudeNext.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
