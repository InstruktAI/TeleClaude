---
id: teleclaude/policy/single-database
type: policy
scope: project
description: The daemon uses a single SQLite database file at the project root.
requires:
  - ../architecture/database.md
---

Policy
- The running daemon uses exactly one database file: teleclaude.db in the project root.
- Do not create additional database files in the main repo.
- Worktrees may have their own teleclaude.db for isolation.
