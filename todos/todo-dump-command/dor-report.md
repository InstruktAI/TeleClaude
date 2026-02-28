# DOR Report: todo-dump-command

## Gate Verdict: PASS (score 8)

Formal DOR gate assessment. All 8 gates satisfied with evidence from codebase verification.

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement is clear: reduce friction for brain dumps via a fire-and-forget CLI command
that scaffolds, registers in roadmap, and emits a notification event. Eight success criteria
are concrete and testable — file creation, slug generation, notification emission, error handling.

### 2. Scope & Size — PASS

Atomic work: one CLI handler + CLI_SURFACE entry in `telec.py`, one spec update, one test file.
Fits a single session. No cross-cutting concerns.

### 3. Verification — PASS

Unit tests for arg parsing, slug generation, error cases, input.md content, and notification
failure resilience. Demo script validates end-to-end. `make test` and `make lint` as standard
quality gates.

### 4. Approach Known — PASS

Codebase verification confirms all referenced patterns exist:

- `_handle_bugs_report` (telec.py:2631) — arg parsing, slug auto-generation, error handling
- `create_todo_skeleton()` (todo_scaffold.py:58) — signature `(project_root, slug, *, after=None) -> Path`
- `add_to_roadmap()` (core/next_machine/core.py) — roadmap registration
- `CLI_SURFACE` schema (telec.py:133) — command definition structure
- `_handle_todo()` router (telec.py:1620) — insertion point for new subcommand

### 5. Research Complete — PASS (auto-satisfied)

No third-party dependencies. Notification service is an internal package with a known API.

### 6. Dependencies & Preconditions — PASS

- `notification-service` dependency explicit in `roadmap.yaml` (`todo-dump-command.after: [notification-service]`)
- notification-service DOR: score 8, status pass (verified in state.yaml)
- Producer API (`emit_event`) defined in notification-service implementation plan

### 7. Integration Safety — PASS

New subcommand — no modification to existing behavior. Notification emission failure is
non-fatal (warning logged, scaffold still succeeds). No destabilization risk.

### 8. Tooling Impact — PASS (auto-satisfied)

No tooling or scaffolding procedure changes.

## Plan-to-Requirement Fidelity

Traced every implementation plan task to requirements:

| Plan Task                 | Requirement                                                    | Fidelity |
| ------------------------- | -------------------------------------------------------------- | -------- |
| 1.1 CLI_SURFACE entry     | Req #1 (new CLI subcommand)                                    | Match    |
| 1.2 Wire in \_handle_todo | Req #1                                                         | Match    |
| 1.3 Handler impl          | Req #1-7 (slug gen, scaffold, input.md, notification, roadmap) | Match    |
| 1.4 Spec update           | Documentation                                                  | Match    |
| 2.1 Tests                 | Req #7 (unit tests)                                            | Match    |

**Roadmap registration logic verified**: Plan step 5 correctly handles the gap where
`create_todo_skeleton` only registers in roadmap when `after` is not `None`. The handler
calls `add_to_roadmap()` directly when `--after` is omitted, matching the requirement that
dump always registers (unlike `create`).

**Slug generation**: Plan correctly omits the `fix-` prefix from `_handle_bugs_report` pattern,
since dump creates feature todos, not bug fixes.

No contradictions found between plan and requirements.

## Assumptions

1. Notification service producer API: `emit_event(event_type, source, level, domain, description, payload)` — per notification-service implementation plan.
2. Redis connection details available via standard notification service mechanism.
3. `todo.dumped` event type listed in notification-service event catalog (Task 5.5).

## Open Questions

None.

## Blockers

None. The `notification-service` dependency is tracked via `roadmap.yaml` and has DOR pass.
