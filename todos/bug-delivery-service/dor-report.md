# DOR Report: bug-delivery-service

## Draft Assessment

**Date:** 2026-02-22
**Phase:** Draft (pending gate validation)

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement is explicit: bugs discovered during AI-assisted development have no fast capture-and-fix mechanism. The solution (fire-and-forget pipeline) is well-defined. Success criteria are concrete and testable (CLI behavior, state machine behavior, file creation, test passing).

### 2. Scope & Size — CAUTION

The plan has 9 implementation tasks touching ~5 files. Cross-cutting changes:

- `core.py` (state machine) — highest risk, central to all orchestration.
- `telec.py` (CLI) — new command enum + handlers.
- `todo_scaffold.py` — new function following existing pattern.
- 2 new agent command files.
- 1 review command modification.

This is on the edge of single-session atomicity. However, many tasks are small and guided by code snippets. The builder should manage if focused. If the gate determines this is too large, splitting options:

- **Split A:** Scaffold + CLI (tasks 1-3) as one todo, state machine + commands (tasks 4-8) as another.
- **Split B:** Infrastructure (tasks 1-5) first, then integration (tasks 6-9).

### 3. Verification — PASS

Clear verification path: unit tests for scaffold and bug detection, `make test`, `make lint`, manual smoke test. Edge cases identified (existing dir, invalid slug, daemon unavailable for dispatch).

### 4. Approach Known — PASS

All patterns exist in the codebase:

- `create_todo_skeleton()` pattern for scaffold.
- `TelecCommand` enum + handler pattern for CLI.
- `check_file_exists()` + bypass pattern for state machine.
- `POST_COMPLETION` dict for worker lifecycle.
- `format_tool_call()` with `note` parameter for conditional behavior.
- `TelecAPIClient.create_session()` for orchestrator dispatch.

### 5. Research Complete — AUTO-PASS

No third-party dependencies introduced. All implementation uses existing project tooling.

### 6. Dependencies & Preconditions — PASS

No prerequisite todos. Bug delivery service is independent of other roadmap items. Required systems (daemon, git) are available in the development environment.

### 7. Integration Safety — PASS

Changes are additive:

- New CLI command doesn't affect existing commands.
- State machine bypass is gated by `bug.md` presence — no behavior change for normal todos.
- New worker command is independent.
- Review/finalize modifications are conditional (only when `bug.md` exists).

### 8. Tooling Impact — NEEDS ATTENTION

This todo changes scaffolding (`todo_scaffold.py`) and introduces a new agent command. After implementation:

- `telec sync` must be run to distribute `next-bugs-fix.md`.
- The scaffolding procedure may need a note about `create_bug_skeleton()` as an alternative entry point.

## Discrepancies Fixed (from external plan)

The original design doc (`docs/plans/2026-02-22-bug-delivery-service-design.md`) contains several references to `state.json` — the project actually uses `state.yaml` with YAML format via Pydantic + `yaml.dump()`. The implementation plan has been corrected to use `state.yaml` throughout.

The external plan's Task 8 used a raw HTTP POST to `/sessions/start` — corrected to use `TelecAPIClient.create_session()` which is the established API client pattern.

## Open Questions

1. **Slug auto-generation:** The plan auto-generates slugs as `fix-{sanitized-description}`. Should there be a max length? (Current plan uses 60 chars — seems reasonable.)
2. **Orchestrator failure:** If the orchestrator session fails mid-pipeline, the bug todo and worktree remain. Should there be a `telec bugs clean` command? (Deferred — can be added later.)

## Draft Score

**Estimated: 7-8/10** — Strong requirements and plan with known patterns. Scope is on the edge. Gate should validate atomicity and confirm the `note`-based finalize adaptation is sufficient.

---

## Gate Verdict

**Date:** 2026-02-22
**Validator:** DOR Gate (automated)
**Final Score: 8/10**
**Status: PASS**

### Gate Results

| Gate                  | Result    | Notes                                                                                                                                                                                                                                                                                                                                                                                                              |
| --------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. Intent & Success   | PASS      | Requirements are explicit, success criteria are concrete and testable.                                                                                                                                                                                                                                                                                                                                             |
| 2. Scope & Size       | PASS      | 9 tasks, ~5 files modified, 2 new files. Definitive call: this fits a single builder session. Most tasks are small, all patterns are verified in the codebase with exact line numbers, and the builder has plan-execution skill. The cross-cutting core.py changes are surgical (3-4 insertion points, each a few lines).                                                                                          |
| 3. Verification       | PASS      | Two new test files, `make test`, `make lint`, manual smoke test. Clear.                                                                                                                                                                                                                                                                                                                                            |
| 4. Approach Known     | PASS      | All patterns verified against actual codebase: `create_todo_skeleton()` at `todo_scaffold.py:44`, `TelecCommand` enum at `telec.py:29`, `check_file_exists()` at `core.py:590`, `POST_COMPLETION` dict at `core.py:81`, `format_tool_call(note=...)` at `core.py:130-136`, `TelecAPIClient.create_session()` at `api_client.py:394`. `TodoState(dor=None)` verified to serialize correctly to `dor: null` in YAML. |
| 5. Research Complete  | AUTO-PASS | No third-party dependencies.                                                                                                                                                                                                                                                                                                                                                                                       |
| 6. Dependencies       | PASS      | Independent of all roadmap items.                                                                                                                                                                                                                                                                                                                                                                                  |
| 7. Integration Safety | PASS      | All changes gated by `bug.md` presence. No behavior change for normal todos.                                                                                                                                                                                                                                                                                                                                       |
| 8. Tooling Impact     | PASS      | `telec sync` is already part of Task 5 and Task 7. No scaffolding procedure update needed — `create_bug_skeleton` is internal to the bug pipeline, not a general-purpose entry point.                                                                                                                                                                                                                              |

### Issues Found and Fixed

**Issue 1 — Non-existent skill reference (Task 5):** The plan referenced `superpowers:systematic-debugging` which does not exist — no skills exist under `agents/skills/`. Fixed: replaced with self-contained debugging instructions in the command, following the same structure as `next-build.md`.

**Issue 2 — Incomplete finalize adaptation (Task 7):** The `note` parameter on `format_tool_call()` instructs the **orchestrator**, but the finalize **worker** independently reads the finalize procedure doc (`docs/global/software-development/procedure/lifecycle/finalize.md`) which explicitly says "Append to `todos/delivered.md`" (step 7) and "Remove from `todos/roadmap.yaml`" (step 8). The worker would still execute those steps regardless of the orchestrator's note. Fixed: added modification of `agents/commands/next-finalize.md` to Task 7, teaching the worker to check for `bug.md` and skip delivered.md/roadmap steps (same conditional pattern as Task 6 for `next-review.md`).

### Open Questions — Dispositioned

1. **Slug auto-generation max length:** Reasonable default, no blocker. Builder can implement a sensible limit (60 chars is fine).
2. **Orchestrator failure cleanup:** Deferred by design — the bug todo and worktree persist as artifacts for manual cleanup. A `telec bugs clean` command can be added later. Non-blocking.

### Scope Rationale

The draft flagged scope as "caution" with 9 tasks. Definitive ruling: **PASS**. Breakdown:

- Tasks 1, 5, 9 are trivial (create template, create command file, run verification).
- Tasks 2, 3 follow exact existing patterns with code snippets provided.
- Task 4 is the most complex but has exact line numbers, verified against actual code.
- Tasks 6, 7 are small conditional additions to existing command files.
- Task 8 extends Task 3's handler — additive, not new architecture.

All 9 tasks touch well-understood code paths with existing patterns. A focused builder session with plan execution will handle this.
