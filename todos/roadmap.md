# Roadmap

> **Last Updated**: 2026-01-08
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Test Suite Quality Cleanup

- [ ] test-cleanup
      Define and enforce test quality standards (requirements-only; no implementation plan yet).

## UI Event Queue

- [>] ui-event-queue-per-adapter
      Create per-adapter UI event queues to avoid cross-adapter bleed.

## Database Schema

(No active items - db-refactor completed and delivered)

## CLI Enhancements

- [.] telec-enhancements
      Transform telec into rich TUI with REST API, multi-tab interface, cross-computer visibility.
      Depends on: db-refactor (for last_message_sent, last_feedback_received columns)
