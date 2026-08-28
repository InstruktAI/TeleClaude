---
description: 'End-to-end dispatch flow when one AI session spawns and supervises another:
  creation, listener registration, execution, and stop-time notification.'
visibility: public
---

# AI-to-AI Dispatch — Design

## Required reads

- @docs/project/spec/session-subscriptions.md
- @docs/project/design/architecture/session-listeners.md

## Purpose

Enable one AI session (the **Initiator**) to spawn and supervise another (the **Worker**) asynchronously, with stop notifications delivered into the Initiator's tmux when the Worker's turn finishes. Supports fire-and-forget delegation, parallel autonomous execution, and asymmetric attention — the Initiator stays focused on its own work while the Worker progresses on the side.

This design covers the dispatch journey. Storage internals for the listener registry live in `session-listeners`. The state contract that this flow obeys lives in `session-subscriptions`.

## Inputs/Outputs

**Inputs:**

- `telec sessions run` or `telec sessions start` invocation from the Initiator (CLI or API). Carries target computer, project path, command or message, and (when relevant) `--direct`.
<!-- planned:personal-assistant-launch -->
- `telec sessions run-pa` invocation from any session. Carries a brief and
  nothing else: no path, no subfolder, no computer, and no person. Each of those
  is derived from the authenticated caller.
<!-- /planned:personal-assistant-launch -->
- Initiator's session identity (`X-Caller-Session-Id` header / equivalent) — pins the dispatcher identity on the new session.
- Worker `agent_stop` events from the agent CLI hook receiver.

**Outputs:**

- New Worker session record in the database, with `initiator_session_id` set.
- Persistent listener row registered for the (Initiator → Worker) pair (`one_shot=false`).
- Stop notification injected into the Initiator's tmux when the Worker's turn ends — subject to the suppression rule in `session-subscriptions`.

## Invariants

<!-- planned:personal-assistant-launch -->
- **A person is derived, never addressed.** `run-pa` resolves its target from the
  authenticated caller's identity. The surface exposes no parameter naming a
  person, in any form.
- **A platform admin gets their own assistant.** The call has one form and
  elevation does not widen it.
- **Person workspaces are unreachable through the general verbs.** `run` and
  `start` refuse a path resolving inside one.
- **No caller identity, no launch.** A caller resolving to no person is refused,
  never defaulted.
- **The launched session is detached.** No initiator is pinned to it and no
  listener is registered for it, so it has no governor and ends itself. The
  caller's identity resolves the person and does not become a parent link.
- **The brief is carried as a request made in the moment.** What `run-pa` starts
  serves that request. Work a schedule already declares is not reachable this way,
  and the launch says so alongside the brief rather than leaving the assistant to
  infer it.
<!-- /planned:personal-assistant-launch -->
- **Initiator pinning.** The dispatcher's session id is stored as `initiator_session_id` on the Worker record at creation time. This is the canonical link from child to parent and survives daemon restart.
- **Listener kind.** Dispatch registers a persistent listener (`one_shot=false`). Repeat dispatches against the same target are deduplicated by `(caller, target)`.
- **No destructive coupling.** Opening a direct link to the Worker does not remove the dispatch-time listener. The link toggles delivery (suppression rule) but never mutates the listener row. Refuted code paths: `unregister_listener(...)` calls inside `_link_direct_sessions` and `_create_direct_link`.
- **Notification source of truth.** Stop events flow through `AgentCoordinator → session_listeners.notify_stop`. No second notification path bypasses the registry.
- **Tmux is the delivery surface.** Listener notifications are injected via `deliver_listener_message` into the Initiator's tmux session, identified by `caller_tmux_session` on the listener row.
- **Suppression while linked.** When a direct link is active between the Initiator and the Worker, listener notifications for that Initiator are skipped. The link's cross-delivery channel carries the relevant signal. See `session-subscriptions` for the canonical rule.

## Primary flows

### 1. Dispatch and registration

```mermaid
sequenceDiagram
    participant Initiator
    participant API as Sessions API
    participant Daemon as Command Service
    participant Listeners as session_listeners
    participant Worker as Worker tmux

    Initiator->>API: POST /sessions { computer, project, command|message }<br/>X-Caller-Session-Id: <initiator_id>
    API->>Daemon: create_session(initiator_session_id=<initiator_id>, ...)
    Daemon->>Daemon: insert sessions row, initiator_session_id pinned
    Daemon->>Listeners: register_listener(target=worker_id, caller=initiator_id, one_shot=false)
    Daemon->>Worker: spawn tmux + agent command
    Daemon-->>API: { session_id: worker_id }
    API-->>Initiator: 200 OK
```

### 2. Stop-time notification (no link active)

```mermaid
sequenceDiagram
    participant Worker
    participant Hook as Hook Receiver
    participant Coord as AgentCoordinator
    participant Listeners as session_listeners
    participant Tmux as deliver_listener_message
    participant Initiator

    Worker->>Hook: agent_stop
    Hook->>Coord: stop event for worker_id
    Coord->>Listeners: notify_stop(target=worker_id)
    Listeners->>Listeners: load listeners for worker_id
    Listeners->>Tmux: deliver to (initiator_id, tc_initiator_<n>)
    Tmux->>Initiator: inject "Session <worker_id> finished its turn..."
```

### 3. Stop-time with an active direct link (suppression path)

```mermaid
sequenceDiagram
    participant Worker
    participant Coord as AgentCoordinator
    participant Listeners as session_listeners
    participant ConvDelivery as conversation_delivery
    participant Initiator

    Worker->>Coord: agent_stop
    Coord->>Listeners: notify_stop(target=worker_id)
    Listeners->>Listeners: load listeners for worker_id
    Listeners->>Listeners: check active direct link (initiator_id, worker_id)
    Note over Listeners: link is active → suppress for this caller
    Listeners-->>Coord: 0 delivered to initiator_id<br/>(other listeners unaffected)
    Coord->>ConvDelivery: schedule debounced cross-delivery for worker_id
    ConvDelivery->>Initiator: bundled turn output via direct link
```

### 4. Caller cleanup

```mermaid
sequenceDiagram
    participant Daemon
    participant Listeners
    participant Links as conversation_links

    Daemon->>Daemon: detect initiator session ended
    Daemon->>Listeners: cleanup_caller_listeners(initiator_id)
    Daemon->>Links: cleanup_session_links(initiator_id)
    Note over Listeners,Links: both axes cleared in one pass
```

## Failure modes

<!-- planned:personal-assistant-launch -->
- **Accepting a person argument and validating it.** This reads as the same
  guarantee reached more flexibly and is a different one: anything a caller can
  pass is something a caller can be talked into passing by content it was asked
  to read. The security property is that no such parameter exists.
- **Shipping `run-pa` while `run` still accepts a person-workspace path.** The
  new verb then sits beside an open door rather than replacing it, and the
  boundary it exists to enforce is no more enforced than before.
<!-- /planned:personal-assistant-launch -->

- **Worker session crashes before any turn completes.** No `agent_stop` ever fires for it; the listener row remains until caller cleanup or explicit unsubscribe. Diagnose via `telec sessions tail <worker_id>` and lifecycle status in the sessions table.
- **Initiator tmux gone before notify.** `deliver_listener_message` logs the failure; the listener row is still removed when it is `one_shot=true`, retained when persistent. Persistent listeners with no live tmux become silent — caller cleanup is the resolution.
- **Daemon restart between dispatch and stop.** Listener rows are durable (SQLite); the registration survives the restart. Recovery requires no caller action.
- **Direct link opened then closed mid-turn.** Suppression toggles cleanly per notify call — the next event after sever delivers normally.
- **Duplicate dispatch against the same worker.** Register is deduped by `(caller, target)`; second attempt is a no-op.
- **Initiator never unsubscribes after worker ends.** Caller-session cleanup removes residual listener rows when the Initiator session itself ends. Until then, the row is idle and harmless.
