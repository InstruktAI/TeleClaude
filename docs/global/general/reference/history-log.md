---
id: general/reference/history-log
type: reference
scope: global
description: Standard format for history.md logs that record request/response entries.
---

# History Log — Reference

## What it is

Defines the required format for `history.md` files that capture request/response
entries over time so agents can reuse prior work instead of redoing it.

## Canonical fields

Each entry must include:

- **Timestamp** (ISO 8601)
- **Objective**
- **Answer**
- **Evidence** (file paths or URLs)
- **Gaps** (unknowns, missing info)

## Allowed values

- **Timestamp**: ISO 8601 string (e.g., `2026-02-03T21:30:00Z`).
- **Evidence**: bullet list of file paths or URLs.
- **Gaps**: bullet list; use `None` if no gaps.

## Known caveats

- Do not overwrite prior entries.
- Append new entries in chronological order (newest last).
- Keep entries concise and scoped to the objective.
