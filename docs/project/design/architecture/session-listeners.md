---
description: Persistent listener registry that notifies callers about the lifecycle
  states of the target sessions they watch, with link-aware suppression.
visibility: public
---

# Session Listeners — Design

## Required reads

- @docs/project/spec/session-subscriptions.md

## Purpose

Persist caller-target subscriptions for passive turn-completion notification, and deliver those notifications into caller tmux sessions — subject to the link-aware suppression rule defined in `session-subscriptions`.

This design owns the listener axis. It does not own the direct-link axis (see `conversation-delivery`) and is not the place to learn the cross-axis contract — see `session-subscriptions` for that.

<!-- planned:session-distress-ingestion -->
The fan-out carries more than one notification kind. Turn-end says the target
finished; the distress kinds say it is stuck or broken. They share the listener
registry, the delivery path, and the message shape, and differ in three
decisions the fan-out makes per kind: whether an active direct link suppresses
delivery, which listener rows form the audience, and what happens when that
audience is empty.
<!-- /planned:session-distress-ingestion -->

## Inputs/Outputs

**Inputs:**

- Listener registration requests from session command handlers:
  - persistent (`one_shot=false`) at orchestrator dispatch time (`create_session` with `initiator_session_id`)
  - one-shot (`one_shot=true`) at non-direct `send_message` time, so the sender hears back when the target's turn completes
- Session stop events from `AgentCoordinator`
<!-- planned:session-distress-ingestion -->
- Session distress events from `AgentCoordinator` — `agent_blocked` and
  `agent_turn_failed`, normalized per `hook-normalized-events`
- Forwarded distress from another computer, naming the target, its computer,
  the distress kind, and the initiator session to deliver to
<!-- /planned:session-distress-ingestion -->
- Unsubscribe requests via `POST /sessions/{id}/unsubscribe`
- Cleanup triggers when caller sessions end

**Outputs:**

- Rows in `session_listeners` (SQLite table)
- Injected notification messages to caller tmux sessions via `deliver_listener_message`
- Boolean confirmations on register / unregister
<!-- planned:session-distress-ingestion -->
- A distress message delivered to the target session's own human-facing
  channel when no persistent listener is watching it
<!-- /planned:session-distress-ingestion -->

## Invariants

- **Durable storage.** Listeners are persisted in SQLite (`session_listeners` table). They survive daemon restart; callers do not need to re-register after a restart.
- **One-shot delivery for `one_shot=true` rows.** These fire once on stop event and are auto-removed.
- **Persistent rows for `one_shot=false`.** Registered at dispatch time. Survive across many turn boundaries. Removed only by explicit unsubscribe or by caller-session cleanup.
- **Deduplication by `(caller, target)`.** At most one row per pair. Repeat registrations are no-ops; the existing `one_shot` value is preserved.
- **Multiple callers allowed per target.** Many callers can listen to the same target.
- **Caller cleanup cascades.** All listeners registered by a caller are removed when the caller session ends.
<!-- planned-change:session-distress-ingestion -->
- **Link-aware suppression.** Notification delivery to a caller is skipped while an active direct link exists between that caller and the target. The listener row is never mutated by link create / close — only delivery is gated. Canonical rule lives in `session-subscriptions`.
<!-- change:session-distress-ingestion -->
- **Link-aware suppression is per notification kind.** Turn-end delivery to a caller is skipped while an active direct link exists between that caller and the target; distress delivery is not. The listener row is never mutated by link create / close — only delivery is gated. Canonical rule lives in `session-subscriptions`.
<!-- /planned-change:session-distress-ingestion -->
- **No destructive coupling.** Creating, reusing, or closing a direct link must not call `register_listener` / `unregister_listener`. Earlier code paths that did so are bugs; the contract forbids them.
- **Cross-restart correctness.** Because rows are durable, restart preserves both persistent and one-shot listeners. A one-shot listener registered before restart will still fire on the next event after restart.
<!-- planned:session-distress-ingestion -->
- **The per-turn notification gate is scoped by `(target, kind)`.** Each
  notification kind is emitted at most once per target turn and is cleared by
  the same next-real-user-entry rule. A distress notification never consumes
  the turn-end notification's gate, and neither distress kind consumes the
  other's.
- **The distress audience is persistent listeners only.** One-shot rows are
  outside it: a distress event neither reads, delivers to, nor removes a
  one-shot row, so its turn-end semantics above are untouched.
- **Every distress event has exactly one recipient class.** When at least one
  persistent listener is registered for the target, distress goes to those
  listeners and the target's human-facing channel receives nothing. When none
  is registered, distress goes to that channel instead. One-shot rows do not
  count as watchers and so never suppress the fallback.
- **The fallback is the session's own output lane, not the platform push
  pipeline.** It is the surface that already carries this session's ordinary
  output. It is not the notification projector's action gate, which addresses
  the admin audience, debounces on a trailing window, and fires on an incident
  fingerprint.
- **Failure is authoritative for the turn it ends.** When a provider emits both
  a turn-end and a turn-failure signal for one turn, the caller's account of
  that turn names the failure; the turn-end signal does not also report that
  turn as complete.
- **The recipient decision is made where the listeners live.** For a target on
  another computer, the origin daemon resolves the audience and the fallback,
  then forwards an already-addressed distress notification. The receiving
  daemon holds no listener rows for a target it did not create and makes no
  audience or fallback decision of its own.
<!-- /planned:session-distress-ingestion -->

## Primary flows

### 1. Listener Registration

```mermaid
sequenceDiagram
    participant Initiator
    participant API as Sessions API
    participant Registry as session_listeners
    participant DB as SQLite

    Initiator->>API: create_session(initiator_session_id=<initiator>, ...)
    API->>DB: INSERT sessions row
    API->>Registry: register_listener(target, caller, tmux, one_shot=false)
    Registry->>DB: INSERT OR IGNORE session_listeners
    alt Newly inserted
        Registry->>API: True (registered)
    else Already present
        Registry->>API: False (dedup, no change)
    end
    API-->>Initiator: 200 OK
```

### 2. Stop Event Notification with Suppression Check

```mermaid
sequenceDiagram
    participant Worker
    participant Coord as AgentCoordinator
    participant Registry as session_listeners
    participant Links as conversation_links
    participant Tmux as deliver_listener_message
    participant Caller

    Worker->>Coord: agent_stop
    Coord->>Registry: notify_stop(target=worker_id)
    Registry->>DB: SELECT listeners WHERE target=worker_id
    loop For each listener
        Registry->>Links: active direct link (listener.caller, worker_id)?
        alt Link present
            Note over Registry: suppress — skip delivery for this caller
        else No link
            Registry->>Tmux: deliver to (caller, caller_tmux_session)
            Tmux->>Caller: inject notification
            opt one_shot row
                Registry->>DB: DELETE session_listeners row
            end
        end
    end
```

### 3. Caller Session Cleanup

```mermaid
sequenceDiagram
    participant Daemon
    participant Registry as session_listeners
    participant DB as SQLite

    Daemon->>Daemon: detect caller session ended
    Daemon->>Registry: cleanup_caller_listeners(caller_id)
    Registry->>DB: DELETE FROM session_listeners WHERE caller_session_id=caller_id
    Registry->>Daemon: count removed
```

### 4. Unsubscribe (umbrella verb)

```mermaid
sequenceDiagram
    participant Caller
    participant API as POST /sessions/{id}/unsubscribe
    participant Registry as session_listeners
    participant Links as conversation_links

    Caller->>API: unsubscribe(target_id)
    API->>Registry: unregister_listener(target_id, caller_id)
    Registry-->>API: listener_removed: bool
    API->>Links: close_link_for_member(caller_id, target_id)
    Links-->>API: link_id | null
    API-->>Caller: { status: success, listener_removed, link_closed, link_id }
```

`unsubscribe` is idempotent — empty state returns success.

### 5. Notification Message Templates

<!-- planned-change:session-distress-ingestion -->
| Event Type | Message Format                                                                            |
| ---------- | ----------------------------------------------------------------------------------------- |
| Stop       | `Session {id} [on {computer}] "{title}" finished its turn. Use: telec sessions tail {id}` |
<!-- change:session-distress-ingestion -->
| Event Type | Message Format |
| ---------- | -------------- |
| Stop | `Session {id} [on {computer}] "{title}" finished its turn. Use: telec sessions tail {id}` |
| Blocked | `Session {id} [on {computer}] "{title}" is waiting on an approval it cannot resolve itself. Use: telec sessions tail {id}` |
| Turn failed | `Session {id} [on {computer}] "{title}" ended its turn on a runtime or provider failure. Use: telec sessions tail {id}` |

Every kind names the target session and states which of the three it is, so a
caller can decide its next move without first tailing the target. The computer
clause and the command's computer selector appear together and only when the
target runs elsewhere, per the locality rule the stop template already follows.
<!-- /planned-change:session-distress-ingestion -->

### 6. Stale Listener Inspection

The listener module exposes `get_stale_targets(max_age_minutes=10)` as a helper for inspection and diagnostics. No daemon-side automatic stale-listener cleanup loop is wired to it today.

<!-- planned:session-distress-ingestion -->
### 7. Distress Notification Fan-out

```mermaid
sequenceDiagram
    participant Worker
    participant Coord as AgentCoordinator
    participant Gate as per-(target,kind) gate
    participant Registry as session_listeners
    participant Caller as persistent listeners
    participant Channel as target's human-facing channel

    Worker->>Coord: agent_blocked | agent_turn_failed
    Coord->>Gate: already emitted this kind this turn?
    alt Already emitted
        Note over Gate: drop — one notice per kind per turn
    else First this turn
        Coord->>Registry: persistent listeners for target?
        alt One or more
            loop For each persistent listener
                Note over Registry: direct-link suppression does NOT apply
                Registry->>Caller: deliver distress message
            end
            Note over Channel: receives nothing
        else None
            Registry->>Channel: deliver distress message
        end
        Coord->>Gate: mark kind emitted for this turn
    end
```

The loop never reads one-shot rows; it neither delivers to them nor removes
them.

For a target whose initiator runs on another computer, the origin daemon runs
this whole decision and then forwards the resulting notification, addressed to
that initiator, over the same request channel the turn-end forward uses. The
forwarded message carries the distress kind so the receiving daemon renders the
matching template rather than a turn-end one.
<!-- /planned:session-distress-ingestion -->

## Failure modes

- **Caller session crash with no clean shutdown.** Cleanup hook may not fire. Listener rows remain until a later caller cleanup pass or until the operator manually unsubscribes. Rows are inert — at worst they suppress on a target that no one is reading.
- **Target session never stops.** Listener row remains until caller cleanup, unsubscribe, or target end.
- **Notification injection fails (tmux gone).** Logged. A `one_shot=true` row is still removed (one-shot semantics preserved). A persistent row is retained; it becomes silent until tmux is restored or the caller is cleaned up.
- **Duplicate registration.** No-op. Returns False to caller; no error.
- **Concurrent stop events for same target.** Listeners load + deliver under per-row locking; double-fire is prevented by the one-shot DELETE being atomic with the SELECT.
- **Suppression check race.** A link severed mid-notify still suppresses for the current event (suppression evaluated at notify time); the next event delivers normally. Cost is at most one missed notification at the exact moment of sever, acceptable because the caller was actively conversing through the link until that moment.
- **Daemon restart with pending one-shot rows.** Rows are durable; the next event after restart fires them.
<!-- planned:session-distress-ingestion -->
- **A provider exposes no native signal for a distress kind.** That kind is
  never produced for targets on that runtime, and no adjacent event is
  substituted for it. Those targets stay exactly as silent in that state as
  before; the caller's vocabulary stays trustworthy for every other runtime.
- **A block resolves immediately after it is reported.** The caller has already
  been told the target was waiting. The per-turn gate bounds this to one notice
  per turn, and the target's turn-end notification still arrives on its own
  gate, so the caller sees the resolution without a separate all-clear.
- **The target has no reachable human-facing channel and no persistent
  listener.** The distress notification has nowhere to land; the failure is
  logged and dropped, as an undeliverable listener notification already is. No
  retry is attempted and the fallback is never redirected to another audience.
- **Distress arrives for a target whose caller is mid-turn.** Delivery uses the
  same control-payload handoff as turn-end, so it lands at the caller's next
  work boundary rather than interrupting a running turn.
<!-- /planned:session-distress-ingestion -->

Direct conversation recovery is owned elsewhere. Restart-safe peer replay is handled by the conversation delivery system, not by this registry.
