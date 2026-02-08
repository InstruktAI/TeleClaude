---
id: 'project/design/architecture/checkpoint-system'
type: 'design'
scope: 'project'
description: 'Checkpoint injection mechanism that delivers structured debrief prompts to AI agents at turn boundaries.'
---

# Checkpoint System — Design

## Purpose

Inject checkpoint messages into AI agent tmux sessions at natural work boundaries, prompting agents to validate their work and capture artifacts. The system uses a unified timer based on the most recent input event, works identically across all agent types, and keeps checkpoint messages invisible to session state.

## Inputs/Outputs

**Inputs:**

- `agent_stop` hook event — Agent's turn ended. Triggers checkpoint evaluation.
- `user_prompt_submit` hook event — New user input. Clears checkpoint state for the new turn.
- `after_model` hook event — Agent finished reasoning. Tracked for other uses but not used in checkpoint decisions.
- Agent restart via API — Triggers unconditional checkpoint injection after a delay.

**Outputs:**

- Checkpoint message injected into the agent's tmux pane via `send_keys`.
- DB field updated: `last_checkpoint_at`.

## Invariants

1. **Unified turn timer**: `turn_start = max(last_message_sent_at, last_checkpoint_at)`. The most recent input event (real user message or previous checkpoint) marks when the agent's current work period began. If `now - turn_start < 30s`, the checkpoint is skipped. This works identically for all agent types.

2. **Checkpoint messages are invisible to session state**: They never persist as user input. `handle_user_prompt_submit` returns early (before notification clearing or DB writes). `_extract_user_input_for_codex` filters them out before writing to `last_message_sent`. The native session transcript retains them as ground truth.

3. **Notification flag preservation**: Checkpoint injections do not clear the notification flag. Only real user input clears it. This prevents users from missing notifications about completed agent work.

4. **Per-turn clearing**: `handle_user_prompt_submit` clears `last_checkpoint_at` and `last_after_model_at` on real user input so each turn starts fresh.

5. **Transcript-based dedup (Codex)**: For agents without `after_model` support (e.g. Codex), an additional check reads the last user message from the session transcript via `extract_last_user_message`. If it matches the checkpoint constant, injection is skipped. This prevents checkpoint-response-stop loops specific to agents that fire `agent_stop` rapidly.

6. **TTS dedup**: Agent output extracted at `agent_stop` is compared against `last_feedback_received` in the session. If identical, summarization and TTS are skipped. This prevents double-speaking when a checkpoint-induced `agent_stop` re-extracts the same output.

7. **DB-persisted state**: Checkpoint state lives in the sessions table (`last_checkpoint_at`, `last_message_sent_at`). No in-memory state. Survives daemon restarts.

8. **Post-restart unconditional injection**: After an agent restart via the API, a checkpoint is injected after a 5-second delay regardless of the 30-second threshold.

## Primary flows

### 1. Normal turn checkpoint (unified timer)

```mermaid
sequenceDiagram
    participant User
    participant Agent
    participant Hook as Hook Receiver
    participant Daemon
    participant DB
    participant Tmux

    User->>Agent: Send message
    Agent->>Hook: user_prompt_submit
    Hook->>Daemon: Deliver event
    Daemon->>DB: Clear last_checkpoint_at, set last_message_sent_at

    Note over Agent: Agent works for 30+ seconds...

    Agent->>Hook: agent_stop
    Hook->>Daemon: Deliver event
    Daemon->>DB: Read last_message_sent_at, last_checkpoint_at
    Daemon->>Daemon: turn_start = max(message_at, checkpoint_at)
    Daemon->>Daemon: elapsed > 30s? Yes
    Daemon->>Tmux: send_keys(CHECKPOINT_MESSAGE)
    Daemon->>DB: Set last_checkpoint_at
```

### 2. Checkpoint response cycle (no re-injection for quick responses)

```mermaid
sequenceDiagram
    participant Tmux
    participant Agent
    participant Hook as Hook Receiver
    participant Daemon
    participant DB

    Tmux->>Agent: Checkpoint message injected
    Agent->>Hook: user_prompt_submit (contains checkpoint text)
    Hook->>Daemon: Deliver event
    Daemon->>Daemon: CHECKPOINT_MESSAGE detected → early return
    Note over Daemon: No DB writes, no notification clearing

    Note over Agent: Agent responds briefly (< 30s)

    Agent->>Hook: agent_stop
    Hook->>Daemon: Deliver event
    Daemon->>DB: Read timestamps
    Daemon->>Daemon: turn_start = last_checkpoint_at (most recent)
    Daemon->>Daemon: elapsed < 30s → skip
```

### 3. Post-checkpoint substantial work (re-injection)

```mermaid
sequenceDiagram
    participant Tmux
    participant Agent
    participant Hook as Hook Receiver
    participant Daemon
    participant DB

    Tmux->>Agent: Checkpoint message injected (checkpoint_at = T=0)
    Agent->>Hook: user_prompt_submit → early return
    Note over Agent: Agent does 45s of real work responding to checkpoint

    Agent->>Hook: agent_stop at T=45
    Hook->>Daemon: Deliver event
    Daemon->>Daemon: turn_start = checkpoint_at (T=0)
    Daemon->>Daemon: elapsed = 45s > 30s → inject
    Daemon->>Tmux: send_keys(CHECKPOINT_MESSAGE)
    Daemon->>DB: Set last_checkpoint_at = T=45
```

### 4. Post-restart checkpoint (unconditional)

```mermaid
sequenceDiagram
    participant API as API Server
    participant Handler as Command Handler
    participant Tmux
    participant DB

    API->>Handler: POST /sessions/{id}/agent-restart
    Handler->>Tmux: Kill old process, start new with --resume
    Handler->>Handler: Schedule async task (5s delay)

    Note over Handler: 5 seconds pass...

    Handler->>Tmux: send_keys(CHECKPOINT_MESSAGE)
    Handler->>DB: Set last_checkpoint_at
```

## Failure modes

| Scenario                                                      | Behavior                                                        | Recovery                                            |
| ------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------- |
| Daemon restart during active turn                             | Timestamps persist in DB; next `agent_stop` evaluates correctly | No action needed                                    |
| DB field missing (migration not run)                          | `AttributeError` on session access                              | Run migration 004; daemon auto-runs on startup      |
| Agent silent after checkpoint                                 | Same output re-extracted at next `agent_stop`                   | TTS dedup skips speaking; DB still updates          |
| Rapid successive stops (< 30s)                                | Checkpoint skipped due to threshold                             | Correct behavior                                    |
| Codex checkpoint loop                                         | Transcript dedup detects own message                            | Correct behavior                                    |
| Both `last_message_sent_at` and `last_checkpoint_at` are None | No turn start → checkpoint skipped                              | First real user message sets `last_message_sent_at` |

## See also

- general/policy/checkpoint — Behavioral policy for agents receiving checkpoints
- general/procedure/checkpoint — Step-by-step protocol for Validate → Capture
- project/spec/event-types — Canonical event type definitions including `after_model`
