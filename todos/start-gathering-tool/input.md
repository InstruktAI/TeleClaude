# start_gathering Tool

Daemon-side implementation of the gathering ceremony launcher and communication fabric. Minimal guidance with just the right amount of tooling — the talking piece and the turn are the only instruments. Everything else is the breath.

## Conceptual Foundation

The gathering is governed by `docs/global/general/procedure/gathering.md` and informed by the Art of Hosting methodology (see third-party docs: `docs/third-party/art-of-hosting/`). The tool codifies the minimal structure that makes collective sensing possible: identity, speaking order, time-boxing, and harvest responsibility. The principles (breath, attunement, proprioception) do the rest.

## Communication Model

Once the gathering is seeded, agents do not use `teleclaude__send_message` to communicate. The tool call is the **handshake** — it establishes the channel. From that point on, agents respond naturally. Their output is injected directly into every other participant's session by the daemon, with attribution headers. No tool calls, no polling. You speak, the circle hears you.

This means:

- The daemon watches the speaking agent's session output
- When the speaking agent produces output, the daemon delivers it to all other sessions as: `"Sage (3):\n\n[their words]"`
- From each agent's perspective, peer contributions appear as injected messages — indistinguishable from any other session input
- A human observing any single session sees the full conversation unfold naturally
- `teleclaude__send_message(direct=true)` is used ONLY at session creation (the seed). After that, it is never called during the gathering. This is mandatory.

**Everything is turn-based.** All communication flows through the talking piece. No parallel messages, no side conversations, no back-and-forth dialogue. The talking piece IS the communication mechanism. Without it, agents message simultaneously and none truly receive.

This model also requires an update to the **Agent Direct Conversation procedure** (`agent-direct-conversation.md`): step 3 ("Converse") currently instructs agents to exchange messages via `teleclaude__send_message(direct=true)` for every exchange. That must be rewritten to match this reality — the tool is the ignition, not the engine.

## Identity and the Seed

Each participant receives a seed message that plants their identity:

- **"You are [Name] ([number]) in this gathering."** — the agent knows who it is
- **The full participant map** — who is who, their numbers, the speaking order, who is the harvester
- **The breath structure** — how many rounds per phase (inhale, hold, exhale), beats per turn
- **The rhythm** — daily, weekly, or monthly
- **The opening question** — from the sub-procedure
- **The proprioception pulse** — auto-gathered system state

The agent reads this and knows: my name, my number, when I speak, and what the structure is. When attributed messages flow in from others, it observes. When the piece arrives at its number — it speaks. Straightforward.

### History as a signal source

The proprioception pulse in the seed must include signals from the **history tool** (`history.py`). Past conversations are one of the most important signal sources — there's so much progression and talking across sessions that critical insights get forgotten. During seed preparation, the daemon (or the initiating agent) should:

- Generate a list of relevant keywords based on the rhythm's scope and recent activity
- Search via `history.py --agent all <keywords>` to surface relevant past conversations
- Include a compressed summary of what surfaced as part of the seed's proprioception pulse

This brings the past into the awareness sphere of the gathering. The agents aren't just sensing the current system state — they're sensing the accumulated conversation history that led to this moment.

## Roles

### Participants (speakers)

Named and numbered members of the circle. They sense, share, and converge through the talking piece. During the **inhale**, each shares independently — not responding to others, but putting signals on the table. They may be influenced or inspired by what they hear, but the inhale is about sensing, not dialogue. During the **hold**, the friction between perspectives does the work. During the **exhale**, convergence is negotiated through the talking piece.

### The Harvester

One participant is designated as the **harvester** in the seed. The harvester:

- **Observes only** during the entire gathering — does not hold the talking piece, does not speak
- Receives all attributed messages from all speakers (same fan-out)
- Listens for what emerges: patterns, tensions, convergences, artifacts taking shape
- **Produces the harvest** at the close — the structured artifacts routed to their natural homes (todos, doc edits, memory entries, vision seeds)
- Writes the **trail entry** — the close synthesis that connects this gathering to the next

The harvester is the system's memory of the ceremony. Their silence is their contribution — they hold the whole while others hold the parts. This role is assigned in the seed, not emergent.

## The Breath Structure

The breath structure is declared upfront in the seed. Each agent knows from the start how many rounds each phase has. This is the container — trusted and non-negotiable.

### Round structure options

| Structure            | Inhale   | Hold     | Exhale   | Character                                                                                                 |
| -------------------- | -------- | -------- | -------- | --------------------------------------------------------------------------------------------------------- |
| **Minimal** (1-1-1)  | 1 round  | 1 round  | 1 round  | Quick pulse — daily standup energy                                                                        |
| **Standard** (2-2-2) | 2 rounds | 2 rounds | 2 rounds | The real minimum for meaningful work: two thoughts to broaden, two rounds to communicate, two to converge |
| **Extended** (2-3-2) | 2 rounds | 3 rounds | 2 rounds | More space for friction in the hold                                                                       |

A "round" = the talking piece goes around the full circle once. With 3 speakers and 2 hold rounds, that's 6 speaking turns in the hold. The harvester does not count as a turn — they observe silently throughout.

**2-2-2 is the recommended minimum.** One round per phase (1-1-1) is for quick daily pulses where the signals are fresh and the scope is narrow. For anything requiring real emergence, two rounds give each phase the space to breathe.

The host guides phase transitions using Note To Self timers. When the round count is reached, the host moves to the next phase. The structure is the container, and the container is trusted.

## The Talking Piece and Thought Heartbeats

Each agent gets a **time window** when holding the talking piece — not a single turn, but a stretch of beats to build a sustained line of thinking. The window is divided into heartbeats (e.g., 3 beats of 60 seconds each).

### The thought heartbeat is a micro-breath inside the macro-breath

Between beats, the creative spark runs freely — the agent builds their thread, accumulates insight, follows where the thought leads. At each beat, the daemon injects a brief grounding prompt into the speaking agent's session:

> _"[Beat 2/3] Signals are here. Is your thread still alive? Continue, pivot, or pass."_

The prompt includes a **micro-pulse** — a compressed snapshot of the live signals relevant to this rhythm's scope. Not the full proprioception dump, just the essential state. This gives the speaker fresh eyes at every beat.

### Three moments at each heartbeat

1. **Sense** — re-read the signals from source (not from memory). What's alive in the system? What did the previous speakers actually say? The refresh prevents building on imagined foundations.
2. **Attune** — does my thread serve the circle, or has it drifted into monologue? The creative spark is free to run, but awareness catches it here if it disconnects from the signals or the circle's need.
3. **Choose** — continue (the thread is alive and grounded), pivot (the refresh revealed a better direction), or pass (silence serves better than more words).

### Turn boundaries

- **Early pass**: The agent can stop and pass at any heartbeat. No obligation to fill the time. Recognizing that listening to fresh input is more valuable than continuing a depleted thread — that IS the contribution.
- **Final beat**: When the last heartbeat fires, the daemon interjects with: _"Your turn is up. What would you like to say last?"_ The agent delivers their closing thought — a distillation, a conclusion, a final signal — or stays silent if everything has already been said. Then the piece passes.
- **Other agents see none of this**: The heartbeat prompts are private to the speaking agent. The circle sees only the sustained contribution — grounded because the speaker kept re-grounding along the way.

### Beat structure per rhythm (proposed)

| Rhythm      | Beats per turn | Beat interval | Turn duration |
| ----------- | -------------- | ------------- | ------------- |
| **Daily**   | 2              | 60s           | ~2 min        |
| **Weekly**  | 3              | 60s           | ~3 min        |
| **Monthly** | 4              | 90s           | ~6 min        |

These are starting values. Adjust after the first live gatherings.

## Phase Discipline

### Inhale (diverge)

Speakers share independently. They put signals on the table — what they notice, what draws attention, what is alive or struggling. **They do not respond to each other.** This is not dialogue. Each contribution stands on its own. Speakers may be influenced by what they hear — that's proprioception at work — but the response lives in their next turn, not in an immediate reply.

### Hold (consolidate under friction)

Now the friction begins. Speakers engage with what was shared. Differences surface. The talking piece still governs — one speaks, all listen — but the content shifts from independent sensing to collective processing. The discipline remains: no interrupting, no side conversations. The friction works through the turn structure.

### Exhale (converge into form)

Convergence is negotiated through the talking piece. Each speaker offers what they see coalescing — not a summary but a distillation. The harvester watches for the artifacts taking shape. When the exhale rounds are complete, the harvester has their material.

## HITL (Human In The Loop)

The human participates as a named member of the circle with a number. Their messages are injected into all sessions with the same attribution format: `"Mo (1):\n\n[their words]"`. Same mechanism, same delivery, same circle. The human is not an observer — they are in the breath.

The human's messages fan out through the same daemon mechanism. When it's their turn, the daemon tracks their heartbeats the same way. The system does not distinguish between human and agent participants in its mechanics — only in the delivery channel.

## Interface

The initiator provides:

- **Rhythm** — daily, weekly, or monthly
- **Participants** — list of names with their numbers and roles (speaker or harvester)
- **Human participant** (optional) — the human's name and number
- **Round structure** — inhale/hold/exhale round counts (or use rhythm defaults)
- **Configuration** (optional) — custom beat counts, intervals, or opening question override

The tool handles everything else: session creation, identity assignment, seed distribution, communication fabric, talking piece management, heartbeat injection, turn transitions, and harvest hand-off.

## Core Behavior

The daemon tool:

1. **Spawns N agent sessions** with `direct=true` — peer topology, no notification chains
2. **Assigns each participant a name, number, and role** — planted in the seed
3. **Distributes the seed message** — identity, participant map, breath structure, rhythm, opening question, proprioception pulse
4. **Manages the communication fabric** — watches speaking agent's output, fans out with attribution, injects into all sessions
5. **Tracks the talking piece** — enforces turn order, manages thought heartbeats, detects pass directives
6. **Manages phase transitions** — tracks round counts, announces phase shifts to all participants
7. **Hands off to the harvester** — at close, the harvester's session receives the signal to produce the harvest
8. **Guard** — prevents nested gatherings (a gathering cannot spawn another gathering)

## Procedure Update Required

The **Agent Direct Conversation procedure** must be updated to reflect the handshake model:

- Step 2 remains: send the introduction with `direct=true`
- Step 3 must change: after the handshake, agents respond naturally. Output is cross-injected by the system. `send_message` is never called again during the conversation. This is not optional.
- The message discipline section already covers economy of expression. Add: the injection model means every word you produce is delivered to all peers. Speak with that awareness.

## Dependencies

- `direct=true` flag on `teleclaude__send_message` and `teleclaude__start_session` (delivered in 6157a769)
- Gathering procedure doc (delivered in c12738c3)
- Rhythm sub-procedures (gathering-rhythm-subprocedures todo)
- Agent Direct Conversation procedure update (new scope — handshake model)
- Art of Hosting third-party docs (delivered: `docs/third-party/art-of-hosting/`)
