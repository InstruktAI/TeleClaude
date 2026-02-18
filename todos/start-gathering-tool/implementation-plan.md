# Implementation Plan: start-gathering-tool

## Approach

Build the gathering tool as a new MCP handler in the existing handlers mixin, with gathering state managed in-memory using an asyncio-locked dictionary. Communication fabric reuses the proven `tmux_bridge` primitives (capture_pane for monitoring, send_keys_existing_tmux for delivery). The talking piece and heartbeat system uses asyncio tasks for timing.

## Architecture

```
start_gathering (MCP tool)
  |
  v
GatheringState (in-memory, asyncio.Lock)
  |-- participants: dict[int, Participant]  (number -> session info)
  |-- current_speaker: int
  |-- beats_remaining: int
  |-- gathering_id: str (UUID)
  |-- rhythm: str
  |-- phase: "seeding" | "active" | "closed"
  |
  v
GatheringOrchestrator (async background task)
  |-- output_monitor: polls speaking session via capture_pane
  |-- heartbeat_timer: asyncio.sleep-based beat injection
  |-- fanout_delivery: loops send_keys_existing_tmux to all non-speaking participants
  |-- pass_detector: pattern match on speaker output for pass directives
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
4. Search history via `history.py --agent all <keywords>` for relevant past conversations — generate keywords from rhythm scope and recent activity, include compressed summary in pulse
5. For each non-human participant: call `_start_local_session(direct=True)` with seed message
6. Seed message contains: identity ("You are [Name] ([number])"), full participant map with roles, breath structure (rounds per phase), rhythm, opening question, proprioception pulse with history signals
7. Build participant map with session IDs and tmux session names
8. Create `GatheringState` in the in-memory store
9. Launch `GatheringOrchestrator` as asyncio background task
10. Return gathering_id and participant map

**Verify:** Tool appears in MCP schema, handler creates sessions and state.

### Task 3: Communication fabric — output monitoring and fan-out

**Files:** `teleclaude/core/gathering.py`

The `GatheringOrchestrator` background task:

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
    await _signal_harvester(state)  # harvester produces artifacts
    await _close_gathering(state)
```

**Phase announcements**: At each phase transition, the daemon injects a message to ALL participants (including harvester): `"--- Phase: HOLD (round 1/2) ---"`. This keeps everyone oriented.

**Harvester signal**: At close, the daemon injects a structured prompt into the harvester's session: the full conversation log, the rhythm, and instructions to produce the harvest (artifacts routed to natural homes + trail entry).

**Output monitoring** (`_monitor_speaker_output`):

1. Capture baseline snapshot of speaking session's pane
2. Poll every 1 second via `capture_pane`
3. Compute delta (new content beyond baseline)
4. If delta detected, call `_fanout_message(state, speaker, delta)`
5. Update baseline to include the delivered content

**Fan-out delivery** (`_fanout_message`):

1. Format: `"[Name] ([number]):\n\n[content]\n"`
2. Loop through all non-speaking participants (including harvester — harvester receives everything)
3. For each: `await tmux_bridge.send_keys_existing_tmux(tmux_session, formatted_message, send_enter=True)`
4. Account for 1-second delay per delivery (sequential, not parallel — tmux safety)

**Verify:** Mock tmux bridge, verify fan-out delivers to all N-1 participants with correct attribution.

### Task 4: Talking piece and heartbeat injection

**Files:** `teleclaude/core/gathering.py`

**Speaker turn loop** (`_run_speaker_turn`):

1. Set `current_speaker` and `current_beat = 1`
2. Capture pane baseline
3. Start output monitor (concurrent with heartbeat timer)
4. For each beat:
   a. `await asyncio.sleep(beat_interval_seconds)`
   b. If pass detected during sleep, break early
   c. Inject heartbeat prompt: `"[Beat {n}/{total}] Signals: {micro_pulse}. Is your thread still alive? Continue, pivot, or pass."`
   d. Increment beat counter
5. After final beat: inject `"Your turn is up. What would you like to say last?"`
6. Wait brief timeout (15-30s) for final response
7. Stop output monitor, record any final output, advance piece

**Pass detection** (`_detect_pass`):

- Run concurrently with output monitoring
- Pattern match on speaker output for: `"I pass to "`, `"I pass the piece"`, `"I pass."`, `"Passing to "`
- Must not match "pass" in normal conversation — require phrase-level matching
- On detection: cancel remaining beats, mark turn as complete

**Heartbeat micro-pulse**: Compressed system state relevant to rhythm scope. For v1, include: number of participants, what phase the gathering is in, how many rounds remain. Richer pulse (channel activity, pipeline state) can be added incrementally.

**Verify:** Timer fires at configured intervals, heartbeat prompts injected, pass detection works, final beat delivers close prompt.

### Task 5: HITL participation

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

For human participants:

- No session is spawned (human has their own session via Telegram/Discord/web)
- The human's `session_id` and `tmux_session_name` are resolved from the caller's session
- Fan-out delivery to the human uses the same `send_keys_existing_tmux` path
- When it's the human's turn, heartbeat prompts are injected into their session
- The human's messages are detected via output monitoring of their session (same mechanism as agents)

**Verify:** Human participant receives attributed messages, heartbeats fire during their turn.

### Task 6: Phase management and harvester

**Files:** `teleclaude/core/gathering.py`

**Phase tracking:**

- The orchestrator loop iterates through inhale → hold → exhale
- Each phase runs for the configured number of rounds (from `BreathStructure`)
- At each phase transition, announce to ALL participants: `"--- Phase: [PHASE] (round [n]/[total]) ---"`
- Track `current_phase` and `current_round` in `GatheringState`

**Harvester hand-off:**

- At close (after exhale rounds complete), inject a structured prompt into the harvester's session
- The prompt contains: summary of what was discussed (or pointer to the full conversation), the rhythm, and instructions to produce the harvest
- The harvester then produces artifacts and the trail entry using their agent capabilities
- The daemon waits for the harvester's output (with a generous timeout) before closing the gathering

**Verify:** Phase transitions fire at correct round boundaries, harvester receives close signal.

### Task 7: History search in seed preparation

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

During seed preparation (before spawning sessions):

1. Generate keyword list based on rhythm scope and recent activity (channel names, active todo slugs, recent commit subjects)
2. Run `history.py --agent all <keywords>` to surface relevant past conversations
3. Compress findings into a brief summary of what surfaced
4. Include in the seed's proprioception pulse as "History signals: [summary]"

This brings past conversations into the gathering's awareness sphere. Agents aren't just sensing current state — they're sensing the accumulated history.

**Verify:** History search runs during seed, results appear in the proprioception pulse.

### Task 8: Nested gathering guard

**Files:** `teleclaude/core/gathering.py`, `teleclaude/mcp/handlers.py`

Before creating a gathering:

- Check `is_in_gathering(caller_session_id)` — scans all active gatherings for the caller's session
- If found, reject with clear error: "Cannot start a gathering from within a gathering"

**Verify:** Attempting to start a nested gathering returns an error.

### Task 9: Tests

**Files:** `tests/unit/test_gathering.py` (new), `tests/integration/test_gathering_tool.py` (new)

Unit tests:

- Gathering state CRUD (create, lookup, close, guard, speakers vs harvester)
- Pass directive detection (positive and negative cases)
- Attribution formatting
- Beat counter advancement
- Phase transition logic (round counting, phase progression)
- Breath structure validation

Integration tests (with mocked tmux bridge):

- Full gathering lifecycle: seed → inhale rounds → hold rounds → exhale rounds → harvester signal → close
- Fan-out delivery to all participants including harvester
- Heartbeat injection at correct intervals
- Early pass detection and turn advancement
- Final beat close prompt
- Phase announcements delivered to all participants
- Harvester excluded from speaking order but receives all messages
- Nested guard rejection
- History search invocation during seed preparation

## Build Sequence

1. Task 1 (state model) — no dependencies
2. Task 2 (MCP tool + handler) — depends on Task 1
3. Task 3 (communication fabric) — depends on Task 1
4. Task 4 (talking piece + heartbeats) — depends on Task 3
5. Task 5 (HITL) — depends on Task 3, Task 4
6. Task 6 (phase management + harvester) — depends on Task 3, Task 4
7. Task 7 (history search in seed) — depends on Task 2
8. Task 8 (nested guard) — depends on Task 1
9. Task 9 (tests) — after each task, but bulk test suite at the end

Tasks 1 and 8 can be built in parallel. Tasks 3 and 4 are tightly coupled and sequential. Task 7 is independent of the communication fabric.

## Risks and Mitigations

| Risk                                                     | Mitigation                                                                              |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Output diff captures injected messages as speaker output | Baseline snapshot resets after each injection; only delta beyond baseline is fanned out |
| Pass detection false positives                           | Conservative phrase matching, require "I pass" at sentence start or standalone          |
| tmux send-keys delay stacks for N participants           | Sequential delivery is correct; document expected latency (~N seconds per message)      |
| Daemon restart loses gathering state                     | Acceptable for v1 — gatherings are ephemeral ceremonies                                 |
| Context exhaustion in long gatherings                    | Fixed round structure (from rhythm sub-procedure) bounds total content                  |
