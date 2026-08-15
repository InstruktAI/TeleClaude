---
visibility: internal
description: Frozen v1 ownership anchor for transcript-derived historical session search.
---

# Session Mirrors Domain Spec — Spec

## What it is

The v1 session-mirrors area derives durable searchable history from native
agent transcripts. Mirrors are historical projections; live session control
remains in agent runtime.

The `telec sessions` and `telec history` command families divide by what they
address. `sessions` addresses the live fleet: a bounded set the caller
enumerates and then acts on — start, message, tail, revive, end. `history`
addresses the archive: unbounded, outliving the sessions in it, and reached by
search rather than enumeration. A verb answering "do this to that session"
belongs to `sessions`; a verb answering "which conversation was that?" belongs
to `history`.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/session_mirrors/`.
- **Implementation roots:** `teleclaude/mirrors/` and history API/CLI surfaces.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement session-history design
  belongs to TeleClaudeNext.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
