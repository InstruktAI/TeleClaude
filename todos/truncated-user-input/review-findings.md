# Review Findings: truncated-user-input

## Scope

Bug fix review. Source of truth: `todos/truncated-user-input/bug.md`.
Reviewed commit range: `$(git merge-base HEAD main)..HEAD`

Changed files in scope:
- `teleclaude/api/streaming.py` — core fix
- `tests/unit/test_api_server.py` — new test

---

## Critical

None.

---

## Important

None.

---

## Suggestions

- **Error path test coverage**: The error path (when `process_message` raises an exception) is not covered by a test. The happy path is well covered by `test_stream_sse_user_message_uses_canonical_process_message_route`, but there is no test asserting that a `process_message` exception causes `convert_session_status("error", session_id)` to be yielded. Low priority since the error handler is straightforward and daemon robustness policy accepts broad-exception-caught.

- **Pre-existing lint gate**: `make lint` exits with an error due to 4 pre-existing loose-dict violations in `teleclaude/cli/tui/animations/general.py`. These are unrelated to this fix and were acknowledged by the builder. The fix itself introduces no new lint violations.

---

## Why No Issues

**Paradigm-fit**: The fix uses `get_command_service().process_message(cmd)` — the identical pattern used in `teleclaude/core/agent_coordinator.py:866` and `agent_coordinator.py:1540`, and the same route used by Telegram/Discord adapters. No new paradigm was introduced; the bypass was removed and the canonical path plugged in.

**Requirements met**: `bug.md` states the fix must route web SSE user messages through the canonical `process_message → inbound_queue → deliver_inbound` path. The diff confirms the direct `tmux_bridge.send_keys_existing_tmux` call was replaced with `ProcessMessageCommand` routed through `get_command_service().process_message(cmd)`. Root cause analysis is sound, fix is minimal and targeted.

**Copy-paste check**: No copy-paste duplication found. The new code reuses existing `ProcessMessageCommand` and `get_command_service` from the shared command layer.

**Lazy import pattern**: The two new lazy imports (`get_command_service`, `ProcessMessageCommand`) inside `_stream_sse` follow the pre-existing pattern already present in the same file (`check_session_access` at line 308, `tmux_bridge` in prior code). The pylint `import-outside-toplevel` rule is configured in pyproject.toml but pylint is not part of the `make lint` pipeline (which uses ruff + pyright + guardrails only), so this is not a regression.

**Test verification**: `test_stream_sse_user_message_uses_canonical_process_message_route` properly patches `teleclaude.core.command_registry.get_command_service`, exercises `_stream_sse` with a user message, and asserts the command fields (`session_id`, `text`, `origin="web"`). The patch target is correct for lazy in-function imports. 82 tests pass, 1 skipped (pre-existing).

---

## Verdict: APPROVE
