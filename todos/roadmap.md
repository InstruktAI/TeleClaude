# Roadmap

> **Last Updated**: 2026-01-11
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## UI Event Queue

- [>] ui-event-queue-per-adapter
  Create per-adapter UI event queues to avoid cross-adapter bleed.

## Test Suite Quality Cleanup

- [>] test-cleanup
      Refactor test suite to verify observable behavior, add docstrings, document system boundaries.

## TUI Testing

- [>] tui-snapshot-tests
      Two-layer TUI testing: view logic tests (get_render_lines) + data flow integration tests (push event → view update pipeline). ~27 tests covering common use cases.
