# Implementation Plan: refactor-agent-readiness

## Overview

Extract agent readiness detection out of `_DaemonSessionMixin` into a focused
`core/agent_readiness.py` module, move marker ownership into `AgentName` metadata,
add readiness lifecycle events, and fix the late-marker re-settle gap. The approach
follows the existing layer ownership pattern: detection is pure (stateless coroutine),
events are facts emitted by the daemon (the caller), and agent metadata lives on
`AgentName` (the enum that already owns per-agent config resolution).

This is a single coherent refactor — all changes share one call chain and are not
independently shippable.

---

## Task 1: Add `prompt_marker` property to `AgentName` enum

**File(s):** `teleclaude/core/agents.py`

- [ ] Add a `prompt_marker` property to `AgentName` that returns the agent-specific
  TUI readiness marker string. Use a private class-level mapping dict keyed by enum
  value, following the same pattern as `AgentConfig` model flags.
  - `CLAUDE` → `"❯ "` (U+276F + space)
  - `GEMINI` → `"Type your message or @path/to/file"`
  - `CODEX` → `"? for shortcuts"`

**Why:** SC-1 requires markers to be agent metadata, not hardcoded in daemon session
logic. `AgentName` already serves as the agent identity enum used across the codebase.
Adding a property here keeps marker knowledge co-located with agent identity, making
it single-site for future agent CLI changes.

**Verification:** Remove xfail markers from
`tests/unit/core/test_agents.py::TestAgentNameMetadataSpec::test_agent_name_has_prompt_marker_property`
and `tests/unit/core/test_agents.py::TestAgentNameMetadataSpec::test_agent_name_returns_correct_marker`.
Both must pass GREEN.

---

## Task 2: Add readiness event types to `events.py`

**File(s):** `teleclaude/core/events.py`

- [ ] Add `"agent_ready"` and `"agent_readiness_timeout"` to the `EventType` Literal
  union.
- [ ] Add `AGENT_READY` and `AGENT_READINESS_TIMEOUT` class attributes to
  `TeleClaudeEvents` with the corresponding string values.

**Why:** SC-4 and SC-5 require the daemon to emit typed events on readiness success
and failure. These events must be in `EventType` for type-safety (the `event_bus.emit`
signature requires `EventType`). Following the existing pattern where every event type
has both a `Literal` entry and a `TeleClaudeEvents` class attribute.

**Verification:** Remove xfail markers from
`tests/unit/core/test_events.py::TestEventsReadinessSpec::test_teleclaude_events_has_readiness_types`
and `test_event_type_includes_readiness_types`. Both must pass GREEN.

---

## Task 3: Create `teleclaude/core/agent_readiness.py` — the readiness detector

**File(s):** `teleclaude/core/agent_readiness.py` (NEW)

- [ ] Create the module with a single public async function:
  ```
  async def wait_for_agent_ready(
      agent_name: str,
      session: Session,
      timeout_s: float,
      quiet_s: float,
      poll_interval_s: float = 0.2,
  ) -> tuple[bool, str]
  ```
- [ ] The function implements the settle-then-marker AND logic:
  1. Resolve the marker from `AgentName.from_str(agent_name).prompt_marker`.
  2. Poll tmux pane output via `tmux_bridge.capture_pane(session.tmux_session_name)`.
  3. Wait for output to change from initial state (has_changed gate).
  4. Wait for output to stabilize (no change for `quiet_s` seconds).
  5. After stabilization, check if the marker is present in the tail.
  6. If marker is present → return `(True, tail)`.
  7. If marker is NOT present → continue polling for the marker up to `timeout_s`.
  8. **SC-6 (late-marker re-settle):** When the marker appears after the initial
     settle window, re-run the stability check to confirm the pane is stable with
     the marker present before returning ready.
  9. If timeout expires without both conditions met → return `(False, last_tail)`.
- [ ] Move `_pane_output_snapshot` logic inline (capture + tail + digest). This is
  a private implementation detail of the detector, not shared infrastructure.
- [ ] The function is stateless — no side effects, no event emission, no DB access.
  It receives a `Session` object and returns a result tuple.

**Why:** SC-2 requires readiness detection to live in dedicated code. Making it a
standalone async function (not a class) keeps it simple — there's no state to manage.
The settle-then-marker AND logic is proven; we're relocating it, not redesigning it.
The `poll_interval_s` parameter replaces the module-level constant from daemon_session
to make the function testable with fast intervals.

**Verification:** Remove xfail markers from all tests in
`tests/unit/core/test_agent_readiness.py`. All four tests must pass GREEN:
- `test_wait_for_agent_ready_settle_then_marker_success`
- `test_wait_for_agent_ready_late_marker_re_settle`
- `test_wait_for_agent_ready_timeout`
- `test_wait_for_agent_ready_fails_when_marker_never_appears`

---

## Task 4: Refactor `daemon_session.py` to consume the detector

**File(s):** `teleclaude/daemon_session.py`

- [ ] Import `wait_for_agent_ready` from `teleclaude.core.agent_readiness`.
- [ ] Remove `AGENT_PROMPT_READY_MARKERS` dict from `daemon_session.py`.
- [ ] Remove `_wait_for_agent_prompt_ready` method from `_DaemonSessionMixin`.
- [ ] Remove `_pane_output_snapshot`, `_wait_for_output_stable`, and
  `_wait_for_output_contains` methods from `_DaemonSessionMixin`. These are readiness
  detection internals that move to the new module.
  - **Caveat:** `_pane_output_snapshot`, `_wait_for_output_change`, and
    `_confirm_command_acceptance` also use pane snapshots for command acceptance
    confirmation (post-injection). Verify whether `_confirm_command_acceptance` and
    `_wait_for_output_change` depend on the same helpers. If they do, keep those
    helpers in daemon_session (they serve command acceptance, not readiness) or
    extract snapshot logic to a shared utility. The builder must trace actual usage
    before removing anything.
- [ ] Rewrite `_handle_agent_then_message` to:
  1. Call `wait_for_agent_ready(agent_name, session, AGENT_PROMPT_READY_TIMEOUT_S, AGENT_START_STABILIZE_QUIET_S)`.
  2. On success (`ready=True`): emit `AGENT_READY` event via `event_bus.emit()`
     with a context containing the `session_id`, then proceed with message injection.
  3. On failure (`ready=False`): emit `AGENT_READINESS_TIMEOUT` event, terminate
     the session via `session_cleanup.terminate_session()`, notify the user via
     `self.client.send_message()`, and return an error result. The current behavior
     logs a warning and proceeds anyway — the new behavior fails closed per SC-5.
- [ ] Keep `_summarize_output_change`, `_wait_for_output_change`, and
  `_confirm_command_acceptance` in daemon_session — they serve command acceptance
  confirmation, not readiness detection.

**Why:** SC-3 requires the daemon's message-injection path to contain no direct
polling or marker knowledge. SC-4 and SC-5 require event emission on success and
failure respectively. The current timeout behavior (warn and proceed) is wrong —
injecting a message into an agent that isn't ready causes lost input. Failing closed
with a user notification is safer.

**Verification:** Remove xfail markers from
`tests/unit/test_daemon_session.py::TestDaemonSessionReadinessSpec`. Both tests must
pass GREEN:
- `test_handle_agent_then_message_emits_ready_event`
- `test_handle_agent_then_message_emits_timeout_event`

---

## Task 5: Update existing daemon_session tests

**File(s):** `tests/unit/test_daemon_session.py`

- [ ] Update any existing tests that mock the removed methods
  (`_wait_for_agent_prompt_ready`, `_wait_for_output_stable`, etc.) to mock
  `wait_for_agent_ready` from the new module instead.
- [ ] Verify all existing daemon_session tests still pass — no regressions from
  the method removal.

**Why:** SC-7 requires existing tests to be updated rather than deleted. The mock
targets change because the methods moved, but the behavioral contracts they test
remain the same.

**Verification:** `pytest tests/unit/test_daemon_session.py -q` — all tests pass,
no xfail markers remain for readiness-related specs.

---

## Task 6: Quality gates

**File(s):** All modified files

- [ ] Run `make lint` — no lint violations, no type errors.
- [ ] Run `make test` — full suite passes.
- [ ] Verify no `AGENT_PROMPT_READY_MARKERS` references remain in daemon_session.py.
- [ ] Verify `_wait_for_agent_prompt_ready` is removed from daemon_session.py.
- [ ] Verify `wait_for_agent_ready` import exists in daemon_session.py.
- [ ] Verify all xfail markers from spec-delivered tests are removed.
- [ ] Validate `todos/refactor-agent-readiness/demo.md` against the delivered behavior.

**Why:** SC-8 and DoD gates. Pre-commit hooks enforce this, but explicit verification
catches issues before the commit attempt.

**Verification:** Clean pre-commit hook run, `telec todo demo validate refactor-agent-readiness`
passes, and no xfail markers remain on any refactor-agent-readiness spec tests.

---

## Referenced Paths

- `teleclaude/core/agents.py`
- `teleclaude/core/events.py`
- `teleclaude/core/agent_readiness.py` (NEW)
- `teleclaude/daemon_session.py`
- `tests/unit/core/test_agent_readiness.py`
- `tests/unit/core/test_agents.py`
- `tests/unit/core/test_events.py`
- `tests/unit/test_daemon_session.py`
