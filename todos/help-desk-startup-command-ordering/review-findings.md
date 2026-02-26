# Review Findings: help-desk-startup-command-ordering

## Summary

Reviewed 6 changed source/test files against requirements, implementation plan,
and project conventions. The implementation is clean, minimal, and well-tested.

## Critical

_(none)_

## Important

_(none)_

## Suggestions

- **`import time` inside function body** (`command_handlers.py:927`): `_wait_for_session_ready` contains `import time` inside the function. Linting policy prefers top-level imports. Move to module top-level for consistency. Non-blocking since `make lint` passes.

## Why No Issues

### Paradigm-Fit Verification

1. **Data flow**: Both changes use the established `db.get_session()` / `db.update_session()` data layer for lifecycle state. No inline hacks, no filesystem bypass, no ad-hoc parsing.
2. **Component reuse**: The new `_wait_for_session_ready` helper is a focused utility with no duplication of existing components. The polling pattern mirrors the existing `_wait_for_output_stable` approach in `daemon.py`.
3. **Pattern consistency**: Logging uses `get_logger(__name__)`, env-configurable constants follow the same `float(os.getenv(...))` pattern as adjacent code. Error handling follows established guard-and-return style.
4. **Copy-paste duplication**: Checked — no duplication found. Each test creates its own mock fixtures appropriate to the scenario.

### Requirements Verification

| Requirement                                                | Code Path                                                                      | Test                                                              |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| FR1.1: process_message MUST NOT inject during initializing | `command_handlers.py:974-989` — gate check + wait                              | `test_process_message_waits_through_initializing_then_dispatches` |
| FR1.2: initializing until bootstrap completes              | `daemon.py:1128-1146` — auto-command before active                             | `test_bootstrap_sets_active_only_after_auto_command_dispatch`     |
| FR2.1: first message after gate opens                      | `command_handlers.py:974-975` — wait then continue                             | `test_process_message_waits_through_initializing_then_dispatches` |
| FR2.2: message remains standalone                          | Existing flow unchanged; no concatenation                                      | `test_discord_first_message_payload_is_standalone`                |
| FR3.1: timeout emits user-visible error                    | `command_handlers.py:977-989` — sends feedback, skips tmux                     | `test_process_message_timeout_skips_tmux_and_sends_feedback`      |
| FR3.2: timeout logged with session id                      | `command_handlers.py:947-950` + `977-979` — warning logs                       | Verified via log assertions in timeout test                       |
| FR4.1: no-auto-command sessions unchanged                  | Gate only triggers on `initializing`; non-auto sessions transition immediately | `test_process_message_active_session_skips_gate`                  |
| FR4.2: headless adoption unchanged                         | Headless check at line 991 runs after gate, orthogonal                         | Existing headless tests remain passing                            |
| FR5.1-5.3: observability logs                              | debug/warning logs at gate-enter, gate-release, timeout                        | Verified via structured logger calls                              |

### Error resilience

- `test_bootstrap_auto_command_error_still_transitions_to_active` proves the session cannot strand in `initializing` if auto-command raises.
- Broad `except Exception` in daemon bootstrap (line 1135) is appropriate — bootstrap must not leave orphaned sessions.

### Manual Verification

Runtime verification requires a running daemon with Discord/help-desk integration. The code paths are fully covered by unit tests. Full runtime validation is appropriately deferred to post-merge (noted in implementation plan Task 4.2).

## Verdict: APPROVE
