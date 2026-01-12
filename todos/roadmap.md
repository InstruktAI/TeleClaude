# Roadmap

> **Last Updated**: 2026-01-12
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Cache Population - Critical Deferred Work

- [>] cache-deferreds
      Complete deferred cache population from data-caching-pushing feature.
      Cache infrastructure exists but is never populated with remote data.
      Remote computers, projects, sessions, todos all missing from TUI.

- [.] cache-per-computer-interest
      Fix architectural flaw: interest tracking must be per-computer, not global.
      Current impl pulls ALL remotes when any interest is registered.
      Expected: only pull data for computers user explicitly expands in TUI tree.
      Depends: cache-deferreds (builds on that infrastructure)

---

## Test Suite Quality Cleanup

- [>] test-cleanup
      Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

