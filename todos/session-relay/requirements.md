# Requirements: session-relay

## Goal

Build a daemon-side session relay primitive that monitors agent output and delivers it to peer sessions, enabling natural agent-to-agent conversation without repeated tool calls.

When `send_message(direct=true)` establishes a peer connection, the daemon starts a bidirectional relay between the two sessions. Both agents produce output naturally; the daemon handles delivery. No additional tool calls needed after the handshake.

## Scope

### In scope

- **Session relay primitive** — given a list of participant sessions, monitor each session's output via `capture_pane` and relay delta to all other participants with attribution. Works for N=2 (1:1) through N=many (future gathering use). Baseline snapshot diffing prevents feedback loops.
- **1:1 relay via `send_message`** — when `send_message(direct=true)` is called, the daemon starts a bidirectional relay between caller and target sessions. Both agents' output is automatically relayed.
- **Relay lifecycle** — relay ends when either session ends or is explicitly stopped.
- **Attribution** — relayed content is formatted as `"[Name] ([number]):\n\n[their words]"` before injection.

### Out of scope

- Turn enforcement, talking piece (gathering todo)
- Heartbeat injection (gathering todo)
- Phase management (gathering todo)
- Harvester role (gathering todo)
- Multi-party orchestration (gathering todo — uses this relay as foundation)
- Persistent relay state (relays are ephemeral, in-memory)

## Communication Model

### The relay primitive

1. A list of participant sessions exists (2 for 1:1)
2. The daemon monitors each active participant's output via `capture_pane`
3. New output (delta beyond baseline) is delivered to all other participants with attribution
4. Baseline resets after each delivery — prevents re-capturing injected content

Both participants are always "active" (no turn enforcement in 1:1 mode).

### 1:1 via send_message

When agent A calls `send_message(session_id=B, message="...", direct=true)`, the daemon:

1. Delivers the message to B's session (existing behavior)
2. Starts a bidirectional relay between A and B
3. B responds naturally — its output is relayed to A with attribution
4. A responds naturally — its output is relayed to B with attribution
5. No further tool calls. The agents just talk.

The relay ends when either session ends, or when one agent explicitly closes the conversation.

The receiving agent does not need to know about the relay. From its perspective, it received a message (typed into its terminal) and it responds. The response appears in the peer's session.

### Feedback loop prevention

When a message is injected into a listener's session, it becomes part of that session's pane content. The daemon must NOT re-capture injected content as "output." The baseline snapshot mechanism handles this: after each delivery, the baseline includes the injected content. Only new content beyond the baseline is captured as delta.

## Success Criteria

- [ ] `send_message(direct=true)` starts a bidirectional relay between caller and target sessions
- [ ] Both agents' output is automatically relayed to the other with attribution
- [ ] No additional tool calls required after the handshake — agents talk naturally
- [ ] Baseline snapshot prevents feedback loops (injected content not re-captured)
- [ ] Relay ends cleanly when either session ends
- [ ] Relay supports N participants (not hardcoded to 2) for future gathering use
- [ ] Full test suite passes (`make test`)
- [ ] Lint passes (`make lint`)

## Key Files (from codebase exploration)

| File                               | What changes                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------ |
| `teleclaude/core/session_relay.py` | New file: relay primitive — data models, output monitoring, fan-out delivery   |
| `teleclaude/mcp/handlers.py`       | Wire relay into `send_message(direct=true)` handler                            |
| `teleclaude/core/tmux_bridge.py`   | Used for injection (`send_keys_existing_tmux`) and monitoring (`capture_pane`) |
| `teleclaude/core/output_poller.py` | Output monitoring pattern reference                                            |
| `teleclaude/core/db_models.py`     | Session lookup for `tmux_session_name` resolution                              |

## Constraints

- Must not break existing session management or notification behavior
- Must not break existing `send_message` behavior when `direct=false`
- Fan-out delivery must handle the 1-second tmux send-keys delay gracefully
- Relay state is in-memory (acceptable to lose on daemon restart)

## Risks

- **Output monitoring latency**: 1-second polling + 1-second send-keys delay means ~2 seconds round-trip for 1:1. Acceptable for conversational pace.
- **Feedback loop edge cases**: If baseline tracking drifts (e.g., tmux pane scrollback limit reached), injected content could be re-captured. Conservative baseline management mitigates this.
- **Daemon restart**: In-memory relay state is lost. The conversation just stops. Acceptable — agents can re-establish via another `send_message`.
