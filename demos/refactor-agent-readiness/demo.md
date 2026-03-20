# Demo: refactor-agent-readiness

## Validation

```bash
# Verify marker metadata lives on AgentName, not in daemon_session
python -c "from teleclaude.core.agents import AgentName; print(AgentName.CLAUDE.prompt_marker, AgentName.GEMINI.prompt_marker, AgentName.CODEX.prompt_marker)"
```

```bash
# Verify AGENT_PROMPT_READY_MARKERS is gone from daemon_session
! grep -q 'AGENT_PROMPT_READY_MARKERS' teleclaude/daemon_session.py && echo "PASS: markers removed from daemon_session"
```

```bash
# Verify new event types exist
python -c "from teleclaude.core.events import TeleClaudeEvents; print(TeleClaudeEvents.AGENT_READY, TeleClaudeEvents.AGENT_READINESS_TIMEOUT)"
```

```bash
# Verify detector module exists and exports the public function
python -c "from teleclaude.core.agent_readiness import wait_for_agent_ready; print('detector module loaded')"
```

```bash
# Verify daemon_session imports the detector
grep -q 'from teleclaude.core.agent_readiness import wait_for_agent_ready' teleclaude/daemon_session.py && echo "PASS: daemon imports detector"
```

```bash
# All readiness spec tests pass (no xfail)
pytest tests/unit/core/test_agent_readiness.py tests/unit/core/test_agents.py::TestAgentNameMetadataSpec tests/unit/core/test_events.py::TestEventsReadinessSpec tests/unit/test_daemon_session.py::TestDaemonSessionReadinessSpec -v
```

```bash
# Full quality gate
make lint && make test
```

## Guided Presentation

### Step 1: Agent metadata owns its markers

Open `teleclaude/core/agents.py`. Each `AgentName` enum member now exposes a
`prompt_marker` property returning the TUI readiness string. This replaces the
`AGENT_PROMPT_READY_MARKERS` dict that was hardcoded in daemon_session.py.

Observe: the markers are the same strings (Claude's `❯ `, Gemini's placeholder text,
Codex's shortcut hint), but now co-located with the agent identity they describe.

### Step 2: Dedicated readiness detector

Open `teleclaude/core/agent_readiness.py`. The `wait_for_agent_ready()` function
encapsulates all pane-polling and marker-detection logic. It resolves the marker from
`AgentName` metadata, implements the settle-then-marker AND logic, and handles the
late-marker re-settle gap (SC-6).

The function is stateless — no side effects, no DB access, no event emission. It
receives a session and returns `(ready: bool, tail: str)`.

### Step 3: Daemon session is now a consumer

Open `teleclaude/daemon_session.py`. The `_handle_agent_then_message` method now calls
`wait_for_agent_ready()` and acts on the result:

- Success → emits `AGENT_READY` event, proceeds with message injection.
- Failure → emits `AGENT_READINESS_TIMEOUT` event, terminates session, notifies user.

The removed methods (`_wait_for_agent_prompt_ready`, `_wait_for_output_stable`,
`_wait_for_output_contains`) no longer exist here. `_pane_output_snapshot` stays in
daemon_session because command-acceptance confirmation still needs it; the detector
only owns readiness polling.

### Step 4: Event-driven lifecycle

Open `teleclaude/core/events.py`. Two new event types — `AGENT_READY` and
`AGENT_READINESS_TIMEOUT` — are added to `EventType` and `TeleClaudeEvents`. These
are facts emitted by the daemon after readiness detection completes. TUI and adapter
subscribers can react to these events for preview-pane timing, error handling, and
future automation.

### Why it matters

Before: daemon_session.py hardcoded agent TUI markers and owned all polling logic —
a layer ownership violation (core reaching into infrastructure+presentation).

After: agent metadata owns markers, a dedicated module owns detection, and the daemon
orchestrates by consuming results and emitting lifecycle events. Clean boundaries,
single-site marker updates, testable detection logic.
