# Tests Agent Guide

This folder is organized for agents to keep test coverage, gaps, and policies consistent.
Use this file as the entrypoint and then follow links to the other markdown files.

## What this document is for

- Orient agents quickly on test scope and priorities.
- Point to the authoritative coverage maps and ignore lists.
- Prevent duplicate or outdated test plans.

## Where to look first (order of operations)

1. `tests/E2E_USE_CASES.md`
   - Master list of end‑to‑end + TUI use cases.
   - Use this to decide what _should_ exist.

2. `tests/integration/USE_CASE_COVERAGE.md`
   - Maps use cases to integration tests + gaps.
   - Use this to decide what’s _missing_.

3. `tests/integration/INTERACTION_COVERAGE_MAP.md`
   - Tracks interaction surface coverage for API/MCP/TUI/Telegram flows.

4. `tests/integration/ALL_MOCKED_VERIFIED.md`
   - Lists fully mocked tests that have been validated; don’t re‑implement them.

5. `tests/ignored.md`
   - Files intentionally without unit tests and why.
   - If you add tests for these files, update this list.

6. `tests/integration/TEST_REORGANIZATION_COMPLETE.md`
   - Historical context for how tests were reorganized.

## How to update docs when tests change

- New integration tests: update `tests/integration/USE_CASE_COVERAGE.md`.
- New E2E/TUI use cases: update `tests/E2E_USE_CASES.md`.
- New mocked tests: update `tests/integration/ALL_MOCKED_VERIFIED.md`.
- Removing or de‑scoping tests: update `tests/ignored.md` with rationale.

## Headless + unified process_message pipeline

- Headless sessions route through the unified `process_message` path.
- Any new tests for headless adoption or routing should be reflected in
  `tests/integration/USE_CASE_COVERAGE.md` (and referenced in `tests/E2E_USE_CASES.md` if applicable).

## Quick pointers

- Unit tests live in `tests/unit/`.
- Integration tests live in `tests/integration/`.
- Snapshots are under `tests/snapshots/`.
