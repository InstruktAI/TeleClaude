REVIEW COMPLETE: bidirectional-agent-links

Critical:

- Unhandled peer-delivery exceptions in linked stop fan-out can abort stop processing and skip downstream lifecycle actions.
  Evidence:
  [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/agent_coordinator.py#L704) invokes `_fanout_linked_stop_output(...)` before worker notification and checkpoint injection.
  Inside fan-out, delivery paths at [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/agent_coordinator.py#L1188) and [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/agent_coordinator.py#L1200) have no per-peer exception guard.
  Concrete trace:

1. `sender_session_id=sender`, peers include one remote entry with `peer.computer_name='RemotePC'`.
2. `self.client.send_request(...)` raises once (network/transport failure).
3. Exception bubbles out of `_fanout_linked_stop_output`.
4. `handle_agent_stop` exits before [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/agent_coordinator.py#L711) and [agent_coordinator.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/agent_coordinator.py#L718).
   Impact:
   Breaks SC-9 coexistence expectations by allowing linked-output transport failures to suppress worker notification/checkpoint steps.

Important:

- `close_link_for_member` can close an unrelated active link when a scoped target does not match any shared link.
  Evidence:
  Target-scoped lookup happens at [session_listeners.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/session_listeners.py#L577). If absent, function falls through to generic caller fallback at [session_listeners.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/session_listeners.py#L583) and severs `links[0]` at [session_listeners.py](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/bidirectional-agent-links/teleclaude/core/session_listeners.py#L587).
  Concrete trace:

1. Caller `A` has active links `{A-B, A-C}`.
2. Request: `close_link=true` with `target_session_id='D'` (typo/stale ID).
3. `get_active_link_between_sessions(A, D)` returns `None`.
4. Function severs the first active link for `A` anyway (`A-B` or `A-C`), violating caller intent.

- Manual verification evidence is incomplete for user-facing cross-computer linked-output behavior.
  Evidence:
  Review executed targeted tests:
  `tests/unit/test_bidirectional_links.py`,
  `tests/unit/test_session_listeners.py`,
  `tests/unit/test_session_cleanup.py`,
  `tests/unit/test_redis_adapter.py` (56 passed).
  Gap:
  No reviewer-side live two-computer/manual trace was performed for end-to-end cross-computer fan-out UX; this must be either verified manually or explicitly waived with owner sign-off.

Suggestions:

- Guard each peer delivery inside `_fanout_linked_stop_output` with try/except and continue fan-out while preserving subsequent stop lifecycle steps.
- Make `close_link_for_member` strict when `target_session_id` is provided: return `None` on no match and do not execute fallback closure.
- Add one integration/functional test that simulates a peer-delivery exception during `agent_stop` and asserts `_notify_session_listener` + `_maybe_inject_checkpoint` still execute.

Paradigm-Fit Assessment:

1. Data flow:
   Uses established DB/session-listener/service boundaries (no inline filesystem bypass).
   Exception isolation at the transport edge is insufficient (critical finding).
2. Component reuse:
   Link behavior is centralized in `db.py` + `session_listeners.py` and reused by handlers/coordinator.
3. Pattern consistency:
   Overall consistent with existing message-processing/event patterns; scoped close-link fallback violates explicit boundary intent by applying unintended side effects.

Verdict: REQUEST CHANGES

## Fixes Applied

### Critical: Unhandled peer-delivery exceptions in linked stop fan-out can abort stop processing

- Fix:
  Added per-peer exception isolation in `_fanout_linked_stop_output` so delivery failures are logged and fan-out continues without aborting `handle_agent_stop` lifecycle steps.
  Added regression test `test_agent_stop_continues_after_linked_output_delivery_error` to assert `_notify_session_listener` and `_maybe_inject_checkpoint` still run when remote send fails.
- Commit: `a0b60384`

### Important: `close_link_for_member` can close an unrelated active link on scoped target miss

- Fix:
  Made `close_link_for_member` strict for scoped close requests: when `target_session_id` is provided and no shared link exists, it now returns `None` and does not execute generic fallback closure.
  Added regression test `test_close_link_for_member_target_miss_does_not_close_other_links`.
- Commit: `acf5e719`

### Important: Manual verification evidence incomplete for cross-computer linked-output UX

- Clarification:
  Attempted live two-computer validation, but only one computer (`MozBook`) is available in this environment at the time of fix (`2026-02-24`), so reviewer-side cross-computer manual trace cannot be executed here.
  As compensating evidence, ran targeted automated cross-computer path coverage including
  `test_agent_stop_continues_after_linked_output_delivery_error` (PASS), which exercises remote peer delivery failure handling.
- Status:
  Manual two-computer trace remains pending owner execution or explicit owner waiver/sign-off.
