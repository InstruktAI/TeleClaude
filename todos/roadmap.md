# Roadmap

> **Last Updated**: 2026-01-09
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## REST Adapter Refactor

- [>] terminal-adapter-refactor
      Unify telec CLI through AdapterClient. RESTAdapter becomes first-class adapter.
      Resume commands for cross-computer session discovery. TUI auto-focus.

## UI Event Queue

- [>] ui-event-queue-per-adapter
  Create per-adapter UI event queues to avoid cross-adapter bleed.

## Test Suite Quality Cleanup

- [.] test-cleanup
      Refactor test suite to verify observable behavior, add docstrings, document system boundaries.
