# Refactor agent readiness detection out of daemon_session.py

## Problem

daemon_session.py directly reads tmux pane output and pattern-matches agent-specific TUI chrome (Claude `───`, Gemini `▀▄`, Codex `›`) to determine when an agent is ready for input. This violates layer ownership (core reaching into infrastructure+presentation), boundary purity (core expressing intent in UI terms), and DIP (high-level session management depending on low-level agent CLI rendering details).

The existing fix-command-injection-latency worktree already fixed 5 issues: spurious Enter keys, idle flush latency, silent error swallowing, fragile text markers, OR→AND readiness logic. But the readiness detection itself remains architecturally wrong — hardcoded in daemon_session.py with no abstraction.

## What stays

The settle + marker AND detection mechanism is sound and stays. Output must settle (stop changing), THEN the agent-specific structural marker must be present. Both gates required.

## What changes

### 1. Move readiness markers into AgentName metadata (agents.py)

Each agent declares its own prompt marker as agent metadata, next to its command template and model flags. The daemon never hardcodes agent TUI knowledge. AGENT_PROMPT_READY_MARKERS dict moves from daemon_session.py to AgentName enum as a property.

### 2. Extract readiness detection into core/agent_readiness.py

A focused module that takes an agent name + session, uses tmux pane polling (same `_wait_for_output_stable` + `_wait_for_output_contains` mechanism), reads the marker from AgentName, and returns `(ready: bool, tail: str)`. This is a stateless coroutine — pure detection, no side effects.

The `_wait_for_output_stable`, `_wait_for_output_contains`, and `_pane_output_snapshot` methods move from daemon_session.py into this module. daemon_session.py becomes a consumer.

### 3. Emit AGENT_READY event through event bus

When readiness is detected, the daemon emits `AGENT_READY` through the existing event bus. The TUI subscribes via websocket. The event is a fact emitted by the daemon (the caller), not by the detection module.

### 4. Emit AGENT_READINESS_TIMEOUT event on failure

When readiness detection times out, the daemon emits `AGENT_READINESS_TIMEOUT`. This event should close the session and notify the user. Future automation can subscribe to mark agents unavailable if timeouts recur.

### 5. Fix C1: late-marker re-settle

The late-marker branch in `_wait_for_agent_prompt_ready` (now in agent_readiness.py) must re-settle after finding a late marker. When the marker appears after initial settle via `_wait_for_output_contains`, re-call `_wait_for_output_stable` to confirm pane is stable with marker present before returning ready.

### 6. daemon_session.py becomes a consumer

`daemon_session._handle_agent_then_message` calls the readiness module, emits the appropriate event, then proceeds with injection on success. It no longer owns any polling, marker, or readiness logic.

### 7. TUI preview pane integration

The TUI already uses `_apply_pending_selection` which checks for `tmux_session_name` before showing preview. `AGENT_READY` arriving via websocket as a `SessionUpdatedEvent` (with a readiness status field) naturally triggers preview pane display at the right moment. The existing `PreviewChanged` message flow handles the rest.

## Architecture

Detection is pure (no side effects). Events are facts emitted by the daemon. The daemon keeps orchestration (wait then inject). The module owns detection (how to determine readiness). Clean boundary.

## Files to modify

- `teleclaude/core/agents.py` — add readiness marker metadata to AgentName
- `teleclaude/core/agent_readiness.py` — NEW: readiness detection module
- `teleclaude/daemon_session.py` — remove readiness logic, consume agent_readiness module
- `teleclaude/core/events.py` — add AGENT_READY and AGENT_READINESS_TIMEOUT event types
- `teleclaude/core/output_poller.py` — may need adjustment if idle flush logic interacts
- `tests/unit/test_daemon_session.py` — update tests for new module boundary
- `tests/unit/core/test_agent_readiness.py` — NEW: focused tests for readiness detection

## Continues from

This continues the fix-command-injection-latency worktree. The 5 original fixes (spurious Enter keys, idle flush, silent errors, structural markers, AND logic) are already committed. This refactor relocates and cleans up the readiness logic that those fixes improved.
