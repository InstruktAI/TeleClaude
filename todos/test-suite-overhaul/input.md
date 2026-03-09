# Input: test-suite-overhaul

## Problem

The test suite has 3,438 test functions across 266 files, but it fails at its primary job: catching regressions. Agents either treat tests as truth and break code, or treat code as truth and break tests. Neither works because the tests aren't behavioral specifications — they're implementation snapshots.

## Data (from audit 2026-03-09)

- **351 source files** under `teleclaude/`, only **13 (3.7%)** have a proper 1:1 test file
- **253 orphan test files** don't map to any single source file — cross-cutting, integration, or legacy
- **81.6% of test files** assert on hard-coded string literals (fragile to any message/constant change)
- **5 files** have 15+ `@patch` decorators each (testing mocks, not behavior)
- **Adapter layer**: zero unit tests. **TUI**: <10% dedicated unit test coverage
- **Documented exceptions** in `tests/ignored.md`: models, events, metadata, constants, logging_config, redis_transport, session_cleanup, voice_message_handler — these have valid reasons for no unit tests

## Root cause

No 1:1 mapping means agents can't find the test for the code they're changing. Cross-cutting orphan tests break unpredictably when any module changes. Hard-coded strings cascade failures through dozens of unrelated tests. Over-mocking means tests pass even when real behavior is broken. No TDD discipline means tests confirm implementation rather than specify behavior.

## Decision

Graduated triage: keep genuinely behavioral tests (~25%), delete junk, restructure everything into strict 1:1 mapping, rewrite as TDD behavioral contracts. Not scorched earth — preserves work that's already correct.

## Module breakdown (worker scope)

| Worker | Source scope | Est. source files |
|--------|-------------|-------------------|
| W1 | `adapters/` | ~10 |
| W2 | `api/` | ~8 |
| W3 | `cli/` (non-TUI) | ~20 |
| W4 | `cli/tui/` | ~50 |
| W5 | `core/` (part 1: models, events, session) | ~20 |
| W6 | `core/` (part 2: state machines, orchestration) | ~20 |
| W7 | `hooks/`, `channels/`, `memory/`, `mirrors/`, `transport/`, `utils/` | ~30 |

## Execution model

- Feature branch: `feat/test-suite-overhaul`
- Workers operate in worktrees off the feature branch
- Each worker does: scaffold 1:1 files → migrate from orphans → triage (keep/rewrite/delete) → write TDD contracts
- Orchestrator integrates worker outputs and runs the full suite
- Target: autonomous 24h operation
