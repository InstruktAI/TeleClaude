# Requirements: start-gathering-tool

## Goal

Build a daemon-side `start_gathering` tool that launches and orchestrates gathering ceremonies. The tool spawns peer agent sessions, manages a communication fabric that fans out each speaker's output to all participants, enforces talking piece turn order with thought heartbeats, and supports human-in-the-loop participation.

This is the technical implementation of the gathering procedure (`docs/global/general/procedure/gathering.md`).

## Scope

### In scope

- **Gathering state model** — in-memory state tracking gathering lifecycle, participants, current speaker, beat counters
- **`start_gathering` MCP tool** — spawns N sessions with `direct=true`, assigns each participant an identity (name + number), distributes seed message with full participant map and rhythm configuration
- **Communication fabric** — daemon monitors speaking agent's output via `OutputPoller`/`capture_pane`, fans out to all other sessions with attribution headers using `tmux_bridge.send_keys_existing_tmux`
- **Talking piece management** — enforces turn order, detects explicit pass directives ("I pass to [agent]"), advances to next speaker; harvester is excluded from the speaking order
- **Thought heartbeats** — daemon injects grounding prompts into the speaking agent's session at configured intervals, with micro-pulse signal snapshot and beat counter
- **Turn boundaries** — graceful close prompt on final beat ("Your turn is up. What would you like to say last?"), early pass honored at any beat
- **Phase management** — tracks round counts per phase (inhale/hold/exhale), announces phase transitions to all participants, manages the breath structure declared in the seed
- **Harvester role** — one participant designated as harvester: receives all messages, never holds the talking piece, produces the harvest and trail entry at close
- **Phase discipline** — inhale: speakers share independently (no responding to each other); hold: friction through the talking piece; exhale: convergence negotiated through turns
- **HITL participation** — human joins as named participant with a number and role, messages fan out with same attribution format
- **Nested gathering guard** — prevent starting a gathering from within a gathering
- **MCP tool definition and schema** — follows existing `tool_definitions.py` patterns

### Out of scope

- Agent Direct Conversation procedure update (separate doc-only todo)
- Rhythm sub-procedures (separate todo: `gathering-rhythm-subprocedures`)
- Trail file creation (separate todo: `gathering-trail-files`)
- Phase transition automation (host manages transitions via Note To Self)
- Persistent gathering history (gatherings are ephemeral; the trail captures the close synthesis)

## Communication Model

Once the gathering is seeded, **`send_message` is never called again**. The tool call is the handshake. After that:

1. The daemon monitors the speaking agent's session output (tmux capture-pane)
2. When new output is detected, the daemon extracts the agent's response
3. The daemon delivers it to all other participant sessions as: `"[Name] ([number]):\n\n[their words]"`
4. Delivery uses `tmux_bridge.send_keys_existing_tmux` — same path as listener notifications
5. Other participants see attributed messages injected directly into their sessions

The speaking agent produces output naturally — no tool calls, no special formatting. The daemon handles attribution and delivery.

### Identity assignment in the seed

Each participant's seed message must establish their identity clearly:

- "You are **[Name]** ([number]) in this gathering."
- The full participant map: who is who, their numbers, the speaking order
- The rhythm, the opening question, the round structure (beats per turn)
- The agent knows its number. When it sees messages attributed to other numbers flowing in, it observes. When the piece reaches its number — either by explicit pass ("I pass to [Name]") or by the daemon announcing "The piece is now with [Name] ([number])" — it speaks.
- The human participant receives the same seed with their assigned number. Same identity, same mechanics.

### Output monitoring design

The key challenge: distinguishing the agent's own output from previously injected messages. Since the talking piece enforces one speaker at a time, the approach is:

- Track a **baseline snapshot** of the speaking session's pane content at the start of their turn
- Poll via `capture_pane` at 1-second intervals (existing `OutputPoller` cadence)
- New content beyond the baseline is the speaker's contribution
- On detected change, fan out the delta to all other sessions
- Reset baseline after each fan-out delivery

### Feedback loop prevention

When a message is injected into a listener's session, it becomes part of that session's pane content. The daemon must NOT re-capture injected content as "output" when it becomes that agent's turn. The baseline snapshot mechanism handles this: when a new speaker starts, the baseline includes all previously injected content.

## Roles

### Speakers

Named and numbered participants who hold the talking piece in turn. During the inhale, speakers share independently — they do not respond to each other. They sense, put signals on the table, and may be influenced by what they hear, but the response lives in their next turn, not an immediate reply. During the hold, friction works through the turn structure. During the exhale, convergence is negotiated.

### Harvester

One participant is designated as harvester in the seed. The harvester:

- Receives all fan-out messages (same as any participant)
- Never holds the talking piece — excluded from the speaking order
- Observes the entire gathering in silence
- At close, receives a signal from the daemon to produce the harvest
- Produces: structured artifacts routed to their natural homes (todos, doc edits, memory entries, vision seeds) and the trail entry

The harvester is the system's memory of the ceremony. Their silence is their contribution.

## Breath Structure

The round structure is declared in the seed. Each participant knows from the start how many rounds each phase has.

| Structure            | Inhale | Hold | Exhale | Character                                    |
| -------------------- | ------ | ---- | ------ | -------------------------------------------- |
| **Minimal** (1-1-1)  | 1      | 1    | 1      | Quick daily pulse                            |
| **Standard** (2-2-2) | 2      | 2    | 2      | Recommended minimum for meaningful emergence |
| **Extended** (2-3-2) | 2      | 3    | 2      | More friction space in the hold              |

A "round" = the talking piece goes around the full circle of speakers once. The harvester does not count as a turn. The daemon tracks round counts and announces phase transitions to all participants.

## Talking Piece and Thought Heartbeats

### Turn structure

Each speaker gets a time window divided into beats:

| Parameter               | Description                           | Example |
| ----------------------- | ------------------------------------- | ------- |
| `beats_per_turn`        | Number of heartbeats per speaker turn | 3       |
| `beat_interval_seconds` | Seconds between heartbeats            | 60      |
| `turn_duration`         | Total time per turn (derived)         | ~3 min  |

These values are provided by the rhythm's sub-procedure (or overridden in the tool call).

### Heartbeat injection

At each beat, the daemon injects into the speaking agent's session:

```
[Beat 2/3] Signals refresh: [micro-pulse]. Is your thread still alive? Continue, pivot, or pass.
```

The micro-pulse is a compressed snapshot of relevant system state (active channels, pipeline status, what previous speakers said — enough to re-ground without overwhelming).

### Turn transitions

- **Early pass**: Speaker says "I pass to [agent]" or "I pass" (next in order). Daemon detects the directive, stops monitoring, advances the piece.
- **Final beat**: Daemon injects: "Your turn is up. What would you like to say last?" Speaker responds (or stays silent). Daemon waits for response or a brief timeout, then advances.
- **Explicit pass detection**: Pattern match on the speaker's output for pass directives. Must not false-positive on the word "pass" in normal conversation — match against "I pass to", "I pass the piece", "passing to".

## HITL Participation

The human is a named participant with a number in the map. Their messages (typed into their chat interface) are delivered to the daemon via the existing message pathway. The daemon attributes and fans out identically: `"Mo (1):\n\n[message]"`.

The daemon tracks the human's heartbeats the same way. When it's their turn, heartbeat prompts are delivered to their session. The system does not distinguish between human and agent in mechanics — only in delivery channel.

## Success Criteria

- [ ] `start_gathering(rhythm, participants, ...)` spawns N sessions with `direct=true` and delivers seed messages with identity assignment
- [ ] Each participant's seed includes: name, number, role, full participant map, breath structure, rhythm, opening question, proprioception pulse
- [ ] Speaking agent's output is automatically fanned out to all other sessions with attribution
- [ ] Talking piece enforces turn order — only current speaker's output is fanned out; harvester never holds the piece
- [ ] Heartbeat prompts are injected into the speaking agent's session at configured intervals
- [ ] Early pass is detected and honored
- [ ] Final beat delivers graceful close prompt
- [ ] Phase transitions tracked by round count — daemon announces phase shifts to all participants
- [ ] Harvester receives all messages but never speaks; receives close signal to produce harvest
- [ ] Human participant's messages are fanned out with same attribution
- [ ] Nested gathering guard prevents starting a gathering within a gathering
- [ ] Gathering state is tracked in-memory with proper async locking
- [ ] History search (via `history.py`) is invoked during seed preparation to surface relevant past conversations as input signals
- [ ] Full test suite passes (`make test`)
- [ ] Lint passes (`make lint`)

## Key Files (from codebase exploration)

| File                                 | What changes                                                                   |
| ------------------------------------ | ------------------------------------------------------------------------------ |
| `teleclaude/mcp/handlers.py`         | New `teleclaude__start_gathering` handler, gathering state management          |
| `teleclaude/mcp/tool_definitions.py` | New tool definition and schema                                                 |
| `teleclaude/mcp_server.py`           | Tool dispatch, `ToolName` enum addition                                        |
| `teleclaude/core/tmux_bridge.py`     | Used for injection (`send_keys_existing_tmux`) and monitoring (`capture_pane`) |
| `teleclaude/core/tmux_delivery.py`   | Fan-out delivery pattern (modeled after `deliver_listener_message`)            |
| `teleclaude/core/output_poller.py`   | Output monitoring pattern reference                                            |
| `teleclaude/core/db_models.py`       | Reference for session model (no new table needed if in-memory)                 |

## Constraints

- Must not break existing session management or notification behavior
- Must use `direct=true` for all spawned sessions (no notification subscriptions)
- Fan-out delivery must handle the 1-second tmux send-keys delay gracefully (sequential delivery to N participants)
- Gathering state is in-memory (acceptable to lose on daemon restart — gatherings are ephemeral)
- The tool must work with the existing MCP server architecture

## Risks

- **Output monitoring latency**: 1-second polling + 1-second send-keys delay per recipient means N participants experience up to N+1 seconds of latency per message. Acceptable for conversational pace but worth monitoring.
- **Feedback loop edge cases**: If an agent's response includes content that looks like a pass directive, the daemon might incorrectly advance the piece. Pattern matching must be conservative.
- **Context window pressure**: Injecting N participants' contributions into each session means each session's context grows at N× the rate. For large gatherings or long turns, this could exhaust context. The fixed round structure mitigates this.
- **Daemon restart during gathering**: In-memory state is lost. The gathering would need to be restarted. Acceptable for v1 — gatherings are short-lived ceremonies.
