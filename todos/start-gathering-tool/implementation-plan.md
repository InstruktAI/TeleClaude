# Implementation Plan: start-gathering-tool

## Approach

Build the gathering ceremony on top of the session relay primitive (delivered by `session-relay` todo). The relay handles output monitoring and fan-out. This todo adds: gathering state, MCP tool, turn-managed orchestration, talking piece, heartbeats, phase management, harvester, HITL, and history search.

## Dependency

**Requires `session-relay` to be delivered first.** The gathering orchestrator uses `create_relay()`, `stop_relay()`, and the relay's fan-out mechanism. For gathering mode, the orchestrator controls which participant's monitor is active (only the current speaker), rather than the relay's default of monitoring all participants simultaneously.

## Architecture

```
SessionRelay (from session-relay todo)
  |-- create_relay, stop_relay, _monitor_output, _fanout
  |
  └── Gathering mode (via start_gathering)
        |-- GatheringState (in-memory, asyncio.Lock)
        |     |-- current_speaker, beats_remaining, phase, round
        |-- GatheringOrchestrator (async background task)
        |     |-- turn enforcement: only current speaker monitored
        |     |-- heartbeat_timer: asyncio.sleep-based beat injection
        |     |-- pass_detector: pattern match on speaker output
        |     |-- phase management: inhale → hold → exhale → close
        |-- harvester: receives all, speaks at close only
```

## Tasks

### Task 1: Gathering state model

**Files:** `teleclaude/core/gathering.py` (new)

Define the in-memory state model:

```python
@dataclass
class Participant:
    number: int
    name: str
    session_id: str
    tmux_session_name: str
    role: str = "speaker"  # "speaker" or "harvester"
    is_human: bool = False

@dataclass
class BreathStructure:
    inhale_rounds: int  # e.g. 2
    hold_rounds: int    # e.g. 2
    exhale_rounds: int  # e.g. 2

@dataclass
class GatheringState:
    gathering_id: str
    relay_id: str  # reference to the underlying SessionRelay
    rhythm: str  # daily, weekly, monthly
    participants: dict[int, Participant]
    speaker_order: list[int]  # speaker numbers only (harvester excluded)
    harvester: int  # harvester's participant number
    current_speaker: int  # current speaker's number
    current_beat: int
    beats_per_turn: int
    beat_interval_seconds: int
    breath: BreathStructure
    current_phase: str  # "inhale", "hold", "exhale", "close"
    current_round: int  # which round within the current phase
    phase_status: str  # "seeding", "active", "closed"
    pane_baseline: str  # baseline snapshot for output diffing

# Module-level state with async lock
_gatherings: dict[str, GatheringState] = {}
_gathering_lock = asyncio.Lock()
```

Provide functions: `create_gathering`, `get_gathering`, `close_gathering`, `is_in_gathering(session_id)` (for nested guard), `get_speakers(gathering_id)` (excludes harvester), `get_harvester(gathering_id)`.

**Verify:** Unit tests for state creation, lookup, guard check.

### Task 2: MCP tool definition and handler

**Files:** `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp_server.py`, `teleclaude/mcp/handlers.py`

Add `start_gathering` to `ToolName` enum and tool definitions:

```python
# Tool parameters
rhythm: str           # "daily", "weekly", "monthly"
participants: list[dict]  # [{name: str, number: int, role: "speaker"|"harvester", is_human: bool}]
inhale_rounds: int = 2
hold_rounds: int = 2
exhale_rounds: int = 2
beats_per_turn: int = 3
beat_interval_seconds: int = 60
opening_question: str = ""  # override, otherwise from sub-procedure
```

Handler flow:

1. Validate inputs (no duplicate numbers, at least 2 speakers + 1 harvester, exactly 1 harvester)
2. Check nested guard: caller must not be in an active gathering
3. Gather proprioception pulse (system state, channel activity, pipeline status)
4. Search history via `history.py --agent all <keywords>` for relevant past conversations
5. For each non-human participant: call `_start_local_session(direct=True)` with seed message
6. Seed message contains: identity, full participant map, breath structure, rhythm, opening question, proprioception pulse with history signals
7. Build participant map with session IDs and tmux session names
8. Create relay via `create_relay(participants)` from session_relay module
9. Create `GatheringState` referencing the relay
10. Launch `GatheringOrchestrator` as asyncio background task
11. Return gathering_id and participant map

**Verify:** Tool appears in MCP schema, handler creates sessions and state.

### Task 3: Gathering orchestrator — turn-managed relay

**Files:** `teleclaude/core/gathering.py`

The `GatheringOrchestrator` wraps the session relay with turn enforcement. Instead of monitoring all participants (as in 1:1), it controls which participant's monitor is active based on the talking piece.

```python
async def run_gathering(gathering_id: str):
    state = await get_gathering(gathering_id)
    for phase in ["inhale", "hold", "exhale"]:
        state.current_phase = phase
        rounds = getattr(state.breath, f"{phase}_rounds")
        await _announce_phase(state, phase)
        for round_num in range(1, rounds + 1):
            state.current_round = round_num
            for speaker_num in state.speaker_order:
                state.current_speaker = speaker_num
                await _run_speaker_turn(state)
    await _signal_harvester(state)
    await _close_gathering(state)
```

**Phase announcements**: inject to ALL participants: `"--- Phase: HOLD (round 1/2) ---"`.

**Harvester signal**: At close, inject structured prompt into harvester's session with instructions to produce the harvest.

**Output monitoring**: Uses the relay's `_monitor_output` for the current speaker only. Start/stop individual monitor tasks as the talking piece moves.

**Fan-out delivery**: Uses the relay's `_fanout` — delivers attributed content to all non-speaking participants including harvester.

**Verify:** Mock tmux bridge, verify turn-managed relay delivers only current speaker's output.

### Task 4: Talking piece and heartbeat injection

**Files:** `teleclaude/core/gathering.py`

**Speaker turn loop** (`_run_speaker_turn`):

1. Set `current_speaker` and `current_beat = 1`
2. Capture pane baseline
3. Start output monitor (concurrent with heartbeat timer)
4. For each beat:
   a. `await asyncio.sleep(beat_interval_seconds)`
   b. If pass detected during sleep, break early
   c. Inject heartbeat: `"[Beat {n}/{total}] Signals: {micro_pulse}. Is your thread still alive? Continue, pivot, or pass."`
   d. Increment beat counter
5. After final beat: inject `"Your turn is up. What would you like to say last?"`
6. Wait brief timeout (15-30s) for final response
7. Stop output monitor, advance piece

**Pass detection** (`_detect_pass`):

- Pattern match on speaker output for: `"I pass to "`, `"I pass the piece"`, `"I pass."`, `"Passing to "`
- Must not match "pass" in normal conversation — require phrase-level matching
- On detection: cancel remaining beats, mark turn as complete

**Verify:** Timer fires at configured intervals, heartbeat prompts injected, pass detection works, final beat delivers close prompt.

### Task 5: HITL participation

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

For human participants:

- No session is spawned (human has their own session via Telegram/Discord/web)
- The human's `session_id` and `tmux_session_name` are resolved from the caller's session
- Fan-out delivery to the human uses the same relay mechanism
- When it's the human's turn, heartbeat prompts are injected into their session
- The human's messages are detected via output monitoring of their session

**Verify:** Human participant receives attributed messages, heartbeats fire during their turn.

### Task 6: Phase management and harvester

**Files:** `teleclaude/core/gathering.py`

**Phase tracking:**

- Orchestrator iterates through inhale → hold → exhale
- Each phase runs for configured rounds (from `BreathStructure`)
- At each phase transition, announce to ALL participants
- Track `current_phase` and `current_round` in `GatheringState`

**Harvester hand-off:**

- At close, inject structured prompt into harvester's session
- Harvester produces artifacts and trail entry using agent capabilities
- Daemon waits for harvester's output (generous timeout) before closing

**Verify:** Phase transitions fire at correct round boundaries, harvester receives close signal.

### Task 7: History search in seed preparation

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

During seed preparation:

1. Generate keyword list from rhythm scope and recent activity
2. Run `history.py --agent all <keywords>`
3. Compress findings into brief summary
4. Include in seed's proprioception pulse as "History signals: [summary]"

**Verify:** History search runs during seed, results appear in proprioception pulse.

### Task 8: Nested gathering guard

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

- Check `is_in_gathering(caller_session_id)` before creating
- Reject with clear error: "Cannot start a gathering from within a gathering"

**Verify:** Nested gathering attempt returns error.

### Task 9: Tests

**Files:** `tests/unit/test_gathering.py` (new), `tests/integration/test_gathering_tool.py` (new)

Unit tests:

- Gathering state CRUD (create, lookup, close, guard, speakers vs harvester)
- Pass directive detection (positive and negative cases)
- Attribution formatting
- Beat counter advancement
- Phase transition logic (round counting, phase progression)
- Breath structure validation

Integration tests (mocked tmux bridge):

- Full gathering lifecycle: seed → inhale → hold → exhale → harvester signal → close
- Fan-out delivery to all participants including harvester
- Heartbeat injection at correct intervals
- Early pass detection and turn advancement
- Final beat close prompt
- Phase announcements delivered to all participants
- Harvester excluded from speaking order but receives all messages
- Nested guard rejection
- History search invocation during seed preparation

## Build Sequence

1. Task 1 (gathering state model) — no internal dependencies
2. Task 2 (MCP tool + handler) — depends on Task 1
3. Task 3 (orchestrator) — depends on Task 1, uses session-relay
4. Task 4 (talking piece + heartbeats) — depends on Task 3
5. Task 5 (HITL) — depends on Task 3, Task 4
6. Task 6 (phase management + harvester) — depends on Task 3, Task 4
7. Task 7 (history search) — depends on Task 2
8. Task 8 (nested guard) — depends on Task 1
9. Task 9 (tests) — written alongside, bulk verification at end

## Risks and Mitigations

| Risk                                           | Mitigation                                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| Pass detection false positives                 | Conservative phrase matching, require "I pass" at sentence start or standalone     |
| tmux send-keys delay stacks for N participants | Sequential delivery is correct; document expected latency (~N seconds per message) |
| Daemon restart loses gathering state           | Acceptable for v1 — gatherings are ephemeral ceremonies                            |
| Context exhaustion in long gatherings          | Fixed round structure (from rhythm sub-procedure) bounds total content             |
