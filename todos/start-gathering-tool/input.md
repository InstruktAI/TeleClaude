# Gathering Ceremony Tool

Daemon-side implementation of the `start_gathering` MCP tool that orchestrates gathering ceremonies. The tool spawns peer sessions, distributes seed messages with identity and breath structure, and runs the ceremony: talking piece, thought heartbeats, phase management, harvester hand-off.

**Depends on `bidirectional-agent-links`** — the shared listener/link primitive handles participant membership and sender-excluded fan-out between participant sessions. This todo layers ceremony orchestration on top.

## Conceptual Foundation

The gathering is governed by `docs/global/general/procedure/gathering.md` and informed by the Art of Hosting methodology (see third-party docs: `docs/third-party/art-of-hosting/`). The tool codifies the minimal structure that makes collective sensing possible: identity, speaking order, time-boxing, and harvest responsibility. The principles (breath, attunement, proprioception) do the rest.

## Communication Model

Once the gathering is seeded, **`send_message` is never called again**. The tool call is the handshake. After that, the shared listener link handles all communication:

- The listener tracks the speaking agent's session output
- When the speaking agent produces output, the listener delivers it to all other sessions with attribution
- From each agent's perspective, peer contributions appear as injected messages
- A human observing any single session sees the full conversation unfold naturally

**Everything is turn-based.** All communication flows through the talking piece. No parallel messages, no side conversations. The talking piece IS the communication mechanism. The gathering orchestrator controls which participant is currently allowed to fan out, layering turn enforcement on top of shared-listener fan-out.

This model also requires an update to the **Agent Direct Conversation procedure** (`agent-direct-conversation.md`): step 3 ("Converse") currently instructs agents to exchange messages via `teleclaude__send_message(direct=true)` for every exchange. That must be rewritten to match shared-link reality — the tool is the ignition, not the engine.

## Identity and the Seed

Each participant receives a seed message that plants their identity:

- **"You are [Name] ([number]) in this gathering."** — the agent knows who it is
- **The full participant map** — who is who, their numbers, the speaking order, who is the harvester
- **The breath structure** — how many rounds per phase (inhale, hold, exhale), beats per turn
- **The rhythm** — daily, weekly, or monthly
- **The opening question** — from the sub-procedure
- **The proprioception pulse** — auto-gathered system state

### History as a signal source

The proprioception pulse in the seed must include signals from the **history tool** (`history.py`). Past conversations are one of the most important signal sources. During seed preparation, the daemon should:

- Generate a list of relevant keywords based on the rhythm's scope and recent activity
- Search via `history.py --agent all <keywords>` to surface relevant past conversations
- Include a compressed summary of what surfaced as part of the seed's proprioception pulse

## Roles

### Participants (speakers)

Named and numbered members of the circle. They sense, share, and converge through the talking piece. During the **inhale**, each shares independently — not responding to others. During the **hold**, the friction between perspectives does the work. During the **exhale**, convergence is negotiated.

### The Harvester

One participant is designated as the **harvester** in the seed:

- **Observes only** during the entire gathering — does not hold the talking piece
- Receives all attributed messages from all speakers (same fan-out)
- **Produces the harvest** at the close — structured artifacts routed to their natural homes
- Writes the **trail entry** — the close synthesis that connects this gathering to the next

## The Breath Structure

| Structure            | Inhale   | Hold     | Exhale   | Character                                    |
| -------------------- | -------- | -------- | -------- | -------------------------------------------- |
| **Minimal** (1-1-1)  | 1 round  | 1 round  | 1 round  | Quick daily pulse                            |
| **Standard** (2-2-2) | 2 rounds | 2 rounds | 2 rounds | Recommended minimum for meaningful emergence |
| **Extended** (2-3-2) | 2 rounds | 3 rounds | 2 rounds | More space for friction in the hold          |

A "round" = the talking piece goes around the full circle once. The harvester does not count as a turn.

## Talking Piece and Thought Heartbeats

Each agent gets a time window when holding the talking piece, divided into heartbeats. Between beats, the agent builds their thread freely. At each beat, the daemon injects a grounding prompt with a micro-pulse of relevant signals.

### Turn boundaries

- **Early pass**: Agent can stop and pass at any heartbeat
- **Final beat**: Daemon injects "Your turn is up. What would you like to say last?"
- **Other agents see none of this**: Heartbeat prompts are private to the speaking agent

## HITL (Human In The Loop)

The human participates as a named member of the circle with a number. Same attribution format, same mechanics, same delivery channel via the shared listener link.

## Dependencies

- `bidirectional-agent-links` todo (shared listener/link primitive — must be delivered first)
- `direct=true` handshake semantics on `send_message` / `start_session`
- Gathering procedure doc (delivered: c12738c3)
- Rhythm sub-procedures (gathering-rhythm-subprocedures todo — soft dependency)
- Agent Direct Conversation procedure update (separate doc-only todo)
- Art of Hosting third-party docs (delivered)
