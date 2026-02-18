# Requirements: start-gathering-tool

## Goal

Build a `start_gathering` MCP tool that orchestrates gathering ceremonies on top of the session relay primitive (delivered by `session-relay` todo). The tool spawns participant sessions, distributes seed messages, and runs the ceremony: talking piece, heartbeats, phase management, and harvester hand-off.

## Dependency

**Requires `session-relay` to be delivered first.** The gathering uses the relay's `create_relay()` to establish the communication fabric and controls which participant's monitor is active based on the talking piece.

## Scope

### In scope

- **Gathering state model** — in-memory state tracking gathering lifecycle, participants, current speaker, beat counters
- **`start_gathering` MCP tool** — spawns N sessions with `direct=true`, assigns each participant an identity (name + number), distributes seed message with full participant map and rhythm configuration
- **Gathering orchestrator** — turn-managed relay: only current speaker's output is monitored and fanned out. Uses the session relay primitive with turn enforcement layered on top.
- **Talking piece management** — enforces turn order, detects explicit pass directives, advances to next speaker; harvester excluded from speaking order
- **Thought heartbeats** — daemon injects grounding prompts into the speaking agent's session at configured intervals with micro-pulse signal snapshot and beat counter
- **Turn boundaries** — graceful close prompt on final beat, early pass honored at any beat
- **Phase management** — tracks round counts per phase (inhale/hold/exhale), announces phase transitions to all participants
- **Harvester role** — one participant designated as harvester: receives all messages, never holds the talking piece, produces harvest at close
- **Phase discipline** — inhale: independent sharing; hold: friction through turns; exhale: convergence negotiated
- **HITL participation** — human joins as named participant with a number
- **History search in seed** — search past conversations via `history.py` during seed preparation
- **Nested gathering guard** — prevent starting a gathering from within a gathering
- **MCP tool definition and schema** — follows existing `tool_definitions.py` patterns

### Out of scope

- Session relay primitive (delivered by `session-relay` todo)
- 1:1 direct conversations (delivered by `session-relay` todo)
- Agent Direct Conversation procedure update (separate doc-only todo)
- Rhythm sub-procedures (separate todo: `gathering-rhythm-subprocedures`)
- Trail file creation (separate todo: `gathering-trail-files`)
- Phase transition automation (host manages transitions via Note To Self)
- Persistent gathering history (gatherings are ephemeral)

## Communication Model

### Gathering communication

Once the gathering is seeded, **`send_message` is never called again**. The tool call is the handshake. After that:

1. The gathering orchestrator activates the current speaker's monitor in the relay
2. When new output is detected, the relay delivers it to all other participant sessions as: `"[Name] ([number]):\n\n[their words]"`
3. Other participants see attributed messages injected directly into their sessions
4. When the talking piece moves, the orchestrator deactivates the previous speaker's monitor and activates the next

### Identity assignment in the seed

Each participant's seed message establishes their identity:

- "You are **[Name]** ([number]) in this gathering."
- The full participant map: who is who, their numbers, the speaking order
- The rhythm, the opening question, the round structure (beats per turn)

### Output monitoring design

The key challenge: distinguishing the agent's own output from previously injected messages. The relay's baseline snapshot mechanism handles this — only delta beyond baseline is captured.

### Feedback loop prevention

The relay's baseline mechanism handles this. When a new speaker starts, the baseline includes all previously injected content.

## Roles

### Speakers

Named and numbered participants who hold the talking piece in turn. During inhale: independent sharing. During hold: friction through turns. During exhale: convergence.

### Harvester

One participant designated in the seed. Receives all fan-out. Never holds the piece. Produces harvest at close.

## Breath Structure

| Structure            | Inhale | Hold | Exhale | Character                                    |
| -------------------- | ------ | ---- | ------ | -------------------------------------------- |
| **Minimal** (1-1-1)  | 1      | 1    | 1      | Quick daily pulse                            |
| **Standard** (2-2-2) | 2      | 2    | 2      | Recommended minimum for meaningful emergence |
| **Extended** (2-3-2) | 2      | 3    | 2      | More friction space in the hold              |

## Talking Piece and Thought Heartbeats

### Turn structure

| Parameter               | Description                           | Example |
| ----------------------- | ------------------------------------- | ------- |
| `beats_per_turn`        | Number of heartbeats per speaker turn | 3       |
| `beat_interval_seconds` | Seconds between heartbeats            | 60      |
| `turn_duration`         | Total time per turn (derived)         | ~3 min  |

### Heartbeat injection

At each beat: `"[Beat 2/3] Signals refresh: [micro-pulse]. Is your thread still alive? Continue, pivot, or pass."`

### Turn transitions

- **Early pass**: "I pass to [agent]" or "I pass" — daemon detects, advances piece
- **Final beat**: "Your turn is up. What would you like to say last?"
- **Pass detection**: phrase-level matching, not word-level

## HITL Participation

Human is a named participant with a number. Messages fan out with same attribution. Heartbeats fire during their turn. System does not distinguish human from agent in mechanics.

## Success Criteria

- [ ] `start_gathering(rhythm, participants, ...)` spawns N sessions with `direct=true` and delivers seed messages with identity assignment
- [ ] Each participant's seed includes: name, number, role, full participant map, breath structure, rhythm, opening question, proprioception pulse
- [ ] Speaking agent's output is automatically fanned out to all other sessions with attribution (via relay)
- [ ] Talking piece enforces turn order — only current speaker's output is fanned out; harvester never holds the piece
- [ ] Heartbeat prompts are injected into the speaking agent's session at configured intervals
- [ ] Early pass is detected and honored
- [ ] Final beat delivers graceful close prompt
- [ ] Phase transitions tracked by round count — daemon announces phase shifts to all participants
- [ ] Harvester receives all messages but never speaks; receives close signal to produce harvest
- [ ] Human participant's messages are fanned out with same attribution
- [ ] Nested gathering guard prevents starting a gathering within a gathering
- [ ] Gathering state is tracked in-memory with proper async locking
- [ ] History search (via `history.py`) is invoked during seed preparation
- [ ] Full test suite passes (`make test`)
- [ ] Lint passes (`make lint`)

## Key Files

| File                                 | What changes                                                           |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `teleclaude/core/gathering.py`       | New: gathering state model, orchestrator, phase management, heartbeats |
| `teleclaude/mcp/handlers.py`         | New `teleclaude__start_gathering` handler                              |
| `teleclaude/mcp/tool_definitions.py` | New tool definition and schema                                         |
| `teleclaude/mcp_server.py`           | Tool dispatch, `ToolName` enum addition                                |
| `teleclaude/core/session_relay.py`   | Used (not modified) — relay primitive from session-relay todo          |

## Constraints

- Must not break existing session management or notification behavior
- Must use `direct=true` for all spawned sessions
- Fan-out delivery via the relay handles 1-second tmux send-keys delay
- Gathering state is in-memory (ephemeral)
- Must work with existing MCP server architecture

## Risks

- **Pass detection false positives**: Conservative phrase matching mitigates
- **Output latency for N participants**: ~N seconds per message via relay fan-out. Acceptable for ceremony pace.
- **Context window pressure**: Fixed round structure bounds total content
- **Daemon restart**: In-memory state lost. Gathering must be restarted.
