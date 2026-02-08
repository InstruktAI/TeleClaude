# Inline Bugs Paradigm — SUPERSEDED

This idea was approved, executed, and evolved into a two-track approach:

- **Inline track** (done): All internal bug discovery → fix immediately, no backlog.
  Docs updated: `bugs-handling.md`, `fixer.md`, `checkpoint.md`, `memory-management.md`.
  Deleted: `todos/bugs.md`, `agents/commands/next-bugs.md`.

- **Maintenance track** (captured as work item): External bug reports via GitHub Issues →
  periodic maintenance runner → `next-bugs` worker in `.bugs-worktree` → PR.
  See: `todos/github-maintenance-runner/input.md`.
