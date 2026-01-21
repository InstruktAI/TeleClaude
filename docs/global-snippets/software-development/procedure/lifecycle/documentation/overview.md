---
description:
  Documentation phase ensuring inline docstrings and snippets match the
  code.
id: software-development/procedure/lifecycle/documentation/overview
requires:
  - software-development/procedure/lifecycle/documentation/sync-docstrings
  - software-development/procedure/lifecycle/documentation/sync-snippets
scope: domain
type: procedure
---

# Documentation Phase

Documentation is a distinct lifecycle phase. It ensures the codebase and its inline documentation are aligned before finalization.

Run the phase in order:

1. **Sync Docstrings** — align inline docstrings/comments with actual code behavior.
2. **Sync Snippets** — regenerate `docs/snippets/` from code + docs.

This phase is atomic and idempotent.
