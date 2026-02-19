# Implementation Plan: session-relay

## Approach

Build a session relay primitive that monitors output from participant sessions and delivers it to all other participants. Wire it into `send_message(direct=true)` for bidirectional 1:1 conversations.

## Architecture

```
SessionRelay (core primitive)
  |-- participants: list of (session_id, tmux_session_name, name, number)
  |-- monitors: per-participant async output polling via capture_pane
  |-- fanout: delivers delta to all other participants with attribution
  |-- baselines: per-participant snapshot for feedback loop prevention
  |
  └── 1:1 mode (via send_message(direct=true))
        |-- bidirectional: both participants monitored simultaneously
        |-- no turn enforcement, no phases
        |-- relay ends when either session ends
```

## Tasks

- [x] Task 1: Session relay primitive

**Files:** `teleclaude/core/session_relay.py` (new)

The core output monitoring and fan-out mechanism:

```python
@dataclass
class RelayParticipant:
    session_id: str
    tmux_session_name: str
    name: str
    number: int

@dataclass
class SessionRelay:
    relay_id: str
    participants: list[RelayParticipant]
    baselines: dict[str, str]  # session_id -> pane baseline
    active: bool = True

# Module-level state
_relays: dict[str, SessionRelay] = {}
_relay_lock = asyncio.Lock()
```

Core functions:

- `create_relay(participants) -> relay_id` — register a relay, initialize baselines via `capture_pane`
- `stop_relay(relay_id)` — mark inactive, cancel monitoring tasks
- `get_relay_for_session(session_id) -> relay_id | None` — lookup by participant
- `_monitor_output(relay, participant)` — async task: poll `capture_pane` every ~1s, compute delta beyond baseline, call `_fanout`
- `_fanout(relay, sender, delta)` — format with attribution (`"[Name] ([number]):\n\n[content]"`), deliver to all other participants via `send_keys_existing_tmux`
- `_update_baseline(relay, session_id, new_content)` — reset after delivery to prevent re-capture

The relay monitors ALL participants simultaneously (bidirectional for 1:1). Monitor tasks run as asyncio background tasks. Each monitor watches for `ProcessExited` to detect session end and trigger relay cleanup.

**Verify:** Unit tests for relay creation, fan-out delivery to N-1 participants, baseline snapshot prevents feedback loops, relay cleanup on session end.

- [x] Task 2: 1:1 relay via send_message

**Files:** `teleclaude/mcp/handlers.py`, `teleclaude/core/session_relay.py`

Wire the relay into `send_message(direct=true)`:

1. In `teleclaude__send_message`, when `direct=true` and `caller_session_id` is present:
   - After delivering the message (existing behavior unchanged)
   - Look up caller's session from DB to get `tmux_session_name`
   - Look up target's session from DB to get `tmx_session_name`
   - Create a 2-participant relay between caller and target
   - Both sessions are monitored bidirectionally
2. The relay runs as background asyncio tasks (no blocking)
3. Either agent's output is automatically relayed to the other with attribution
4. Relay ends when either session ends (detected via monitor task)

The receiving agent sees the message arrive (existing send_keys injection) and responds naturally. Its response is captured by the relay and injected into the sender's session.

**Verify:** Integration test — send_message with direct=true starts relay, both directions work, relay cleans up on session end.

- [x] Task 3: Tests

**Files:** `tests/unit/test_session_relay.py` (new)

Unit tests:

- Relay creation with N participants, baseline initialization
- Fan-out delivery to N-1 participants with correct attribution formatting
- Baseline snapshot prevents feedback loops (injected content not re-captured as delta)
- Relay cleanup on session end (stop_relay, get_relay_for_session returns None)
- Multiple concurrent relays don't interfere

Integration tests (with mocked tmux bridge):

- `send_message(direct=true)` starts bidirectional relay
- Output from A appears in B's session with attribution
- Output from B appears in A's session with attribution
- Relay ends when either session ends
- Existing `send_message(direct=false)` behavior unchanged

## Build Sequence

1. Task 1 (relay primitive) — no dependencies. Foundation.
2. Task 2 (1:1 wiring) — depends on Task 1.
3. Task 3 (tests) — written alongside Tasks 1-2, bulk verification at end.

## Risks and Mitigations

| Risk                                   | Mitigation                                                                |
| -------------------------------------- | ------------------------------------------------------------------------- |
| Injected content re-captured as output | Baseline snapshot resets after each injection; only delta beyond baseline |
| tmux pane scrollback overflow          | Conservative baseline — track position, not full content if pane is large |
| Daemon restart loses relay             | Acceptable — agents can re-establish with another send_message            |
| Race condition in concurrent relay ops | asyncio.Lock on \_relays dict, same pattern as \_active_pollers           |
