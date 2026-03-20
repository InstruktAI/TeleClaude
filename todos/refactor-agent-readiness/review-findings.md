# Review Findings: refactor-agent-readiness

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)

## Scope

Lane table: all "Always" lanes executed. Conditional lanes: types (N/A — no new types
added beyond Literal entries), docs (N/A — no CLI/config/API changes), simplify (deferred
until other lanes pass).

## Scope Verification

All 8 success criteria (SC-1 through SC-8) are implemented:

- **SC-1:** `AgentName.prompt_marker` property returns agent-specific marker from
  `_PROMPT_MARKERS_BY_AGENT`. Markers no longer hardcoded in daemon_session.
- **SC-2:** `teleclaude/core/agent_readiness.py` encapsulates all pane-polling and
  marker detection logic in `wait_for_agent_ready()`.
- **SC-3:** `_handle_agent_then_message` calls the detector and acts on the result.
  No direct polling or marker knowledge remains in daemon_session.
- **SC-4:** `AGENT_READY` event emitted via `event_bus.emit()` on success.
- **SC-5:** `AGENT_READINESS_TIMEOUT` emitted on failure, session terminated via
  `session_cleanup.terminate_session()`, user notified via `client.send_message()`.
- **SC-6:** Late-marker re-settle is naturally handled by the loop structure — any
  pane change (including marker appearance) resets `quiet_since`, requiring a new
  quiet window before returning ready.
- **SC-7:** Old tests updated (not deleted), new focused tests added for all boundaries.
- **SC-8:** `make lint` and `make test` pass cleanly.

No gold-plating observed. Delivery matches requirements precisely.

No findings.

## Completeness

All implementation-plan tasks are checked (`[x]`). No `deferrals.md` exists.

No findings.

## Code Review

Production code reviewed for bugs, pattern violations, and quality.

- **agents.py:** `_PROMPT_MARKERS_BY_AGENT` uses `AgentName.*.value` as keys. If a new
  `AgentName` member is added without updating the dict, `prompt_marker` raises `KeyError`
  at runtime. This is correct fail-fast behavior, and the parametrized test covers all
  current members. Acceptable.
- **agent_readiness.py:** Stateless async function, clean separation, no side effects.
  Accepts `Session` object but only accesses `tmux_session_name` — mild coupling but
  acceptable since Session is a TYPE_CHECKING import.
- **daemon_session.py:** Fail-closed behavior (terminate + notify on timeout) is safer
  than the original warn-and-proceed. Event emission correctly uses
  `SessionLifecycleContext` with session_id.
- **events.py:** New Literal entries and class attributes follow established pattern.

No findings.

## Paradigm-fit

- Data flow: Uses existing `tmux_bridge.capture_pane()` and `event_bus.emit()` patterns.
- Component reuse: `_capture_snapshot` mirrors the existing `_pane_output_snapshot` logic
  in daemon_session (which stays for command-acceptance use). No copy-paste of
  parameterizable components.
- Pattern consistency: Async function pattern matches codebase conventions. Event types
  follow established `TeleClaudeEvents` pattern.

No findings.

## Principle Violation Hunt

### Fallback & Silent Degradation

The old code had an unjustified fallback: marker-not-found → inactivity-only detection.
The new code removes this and fails closed. No unjustified fallback paths remain.

### Fail Fast

`AgentName.from_str()` raises `ValueError` on unknown agent. `_PROMPT_MARKERS_BY_AGENT`
raises `KeyError` on missing entry. Both are correct fail-fast behavior.

### DIP

Core module imports only from core (`teleclaude.core.agents`, `teleclaude.core.tmux_bridge`,
`teleclaude.constants`). No adapter imports. No layer violations.

### Coupling / Law of Demeter

`wait_for_agent_ready` accesses `session.tmux_session_name` — one dot, no deep chains.
No god-object dependencies introduced.

### SRP

`agent_readiness.py` has one responsibility (readiness detection). Clean.

### YAGNI / KISS

Minimal implementation. No unnecessary abstractions, no premature configurability.

### Encapsulation / Immutability

`_capture_snapshot` is private. No shared mutable state. Function is stateless.

No findings.

## Security

- No secrets, credentials, or tokens in the diff.
- No sensitive data in log statements (tail output logged only at debug level, truncated).
- No injection vectors (no shell commands, no SQL, no template interpolation).
- No authorization gaps (readiness detection is internal daemon logic).
- Error messages don't leak internal paths (user gets a generic failure message).

No findings.

## Test Coverage

64 tests pass across all 4 test files. All tests are parametrized for all 3 agents.

- SC-1: `TestAgentNameMetadataSpec` (2 tests, parametrized)
- SC-2/SC-3: `TestDaemonSessionReadinessSpec::test_handle_agent_then_message_emits_ready_event`
  verifies `tmux_bridge.capture_pane` not called directly by daemon.
- SC-4: Both success-path tests verify `AGENT_READY` emission with session_id.
- SC-5: Both timeout tests verify `AGENT_READINESS_TIMEOUT` emission, termination, notification.
- SC-6: `test_wait_for_agent_ready_late_marker_re_settle` (parametrized × 3) with
  `call_count >= 7` assertion proving both settle windows.
- SC-7: Old tests updated (mock targets changed), new tests added.
- SC-8: All hooks pass.

No xfail markers remain in scope. Exact-string assertions on markers are permitted
(execution-significant tokens). No prose-lock assertions found.

No findings.

## Silent Failure Detection

The old code's silent degradation (warn + proceed on timeout) has been replaced with
explicit failure (terminate + notify + error return). No log-and-continue patterns in
changed code. No broad exception catches in the new code.

No findings.

## Comment Analysis

No findings.

## Logging

No findings (remediated during review — see below).

## Demo

`telec todo demo validate` passes with 7 executable blocks. All blocks exercise real
code paths: module imports, grep assertions, pytest runs, and `make lint && make test`.
Commands use actual module paths that exist in the codebase. No fabricated output.

No findings.

## Resolved During Review

### R-1: Missing logging in agent_readiness.py (was Important)

**Location:** `teleclaude/core/agent_readiness.py`
**What:** The extracted readiness detector had zero logging — no logger import, no
diagnostic output. The original code in `daemon_session.py` logged stabilization
success, timeout, and marker detection events. This was an observability regression
violating DoD §8.
**Fix:** Added `from instrukt_ai_logging import get_logger` and `logger = get_logger(__name__)`.
Added `logger.debug()` calls at the two exit points: success (settled with marker)
and timeout (with `has_changed` state and elapsed time for diagnosis).
**Validation:** All 12 detector tests pass. Pyright reports 0 errors.

### R-2: Missing inline comments on new event types (was Suggestion)

**Location:** `teleclaude/core/events.py:344-345`
**What:** `AGENT_READY` and `AGENT_READINESS_TIMEOUT` in `TeleClaudeEvents` lacked the
semantic description comments that all other event types in the class carry.
**Fix:** Added `# Fact: agent TUI is stable at input prompt.` and
`# Fact: agent TUI did not reach ready prompt within timeout.`

## Why No Issues

After resolving R-1 and R-2, no unresolved findings remain:

1. **Paradigm-fit:** Verified against existing async patterns, event-bus usage,
   tmux_bridge interaction, and `TeleClaudeEvents` class conventions.
2. **Requirements met:** All 8 SC criteria verified against implementation with
   specific code locations traced.
3. **Copy-paste checked:** `_capture_snapshot` in agent_readiness mirrors
   `_pane_output_snapshot` in daemon_session. Both are needed — daemon_session's
   copy serves command-acceptance confirmation (different call chain). No
   parameterizable component was duplicated.
4. **Security reviewed:** No secrets, injection vectors, auth gaps, or info leakage
   in the diff.

## Verdict

**APPROVE**

Unresolved Critical: 0
Unresolved Important: 0
Suggestions: 0 (all addressed inline)
