---
description: 'Contract for the two-axis subscription model between caller and target
  sessions: passive listener and active direct link.'
visibility: public
---

# Session Subscriptions — Spec

## What it is

The subscription contract between a **caller** session and a **target** session — the canonical answer to "what states can the (caller, target) pair occupy and what verbs change them."

Two orthogonal axes of subscription exist. Each axis is an independent record with an independent lifecycle. They are not alternatives — a caller may hold zero, one, or both toward the same target.

- **Listener** (passive). "Notify me when the target's turn state changes." Backed by a row in `session_listeners`. Drives `notify_stop` and `notify_input_request` deliveries into the caller's tmux.
- **Direct link** (active). "I am in two-way conversation with the target." Backed by rows in `conversation_links` + `conversation_link_members`. Drives transcript-based cross-delivery of turn output between peers.

The spec defines the state model, the verbs, and the runtime interaction (notification suppression while a link is active). Internal mechanism for each axis lives in the corresponding design snippets.

## Canonical fields

### Subscription state

For any `(caller_session_id, target_session_id)` pair, the subscription state is:

```
SubscriptionState = {
  listener: ListenerRecord | null,
  link:     LinkRecord     | null,
}
```

### `ListenerRecord`

| field                 | type    | meaning                                                                                                            |
| --------------------- | ------- | ------------------------------------------------------------------------------------------------------------------ |
| `target_session_id`   | str     | session whose turn events trigger notifications                                                                    |
| `caller_session_id`   | str     | session that receives notifications                                                                                |
| `caller_tmux_session` | str     | tmux destination for notification injection                                                                        |
| `registered_at`       | iso8601 | wall time of registration                                                                                          |
| `one_shot`            | bool    | if true, removed automatically after first notify; if false, persists until explicit unsubscribe or caller cleanup |

### `LinkRecord`

| field        | type             | meaning                                                                               |
| ------------ | ---------------- | ------------------------------------------------------------------------------------- |
| `link_id`    | uuid             | identity of the conversation link                                                     |
| `mode`       | enum             | `direct_link` (two-member peer) or `gathering_link` (multi-member; out of scope here) |
| `members`    | list[session_id] | caller and target are both members for a direct link                                  |
| `severed_at` | iso8601 \| null  | when the link was closed; absent for active links                                     |

### Verbs

| verb                                           | effect on `listener`                                                   | effect on `link`                                            | idempotent |
| ---------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------- | ---------- |
| `dispatch_child` (orchestrator spawns a child) | inserts persistent listener (`one_shot=false`)                         | —                                                           | yes        |
| `sessions send` (non-direct)                   | inserts one-shot listener (`one_shot=true`) if none present            | —                                                           | yes        |
| `sessions send --direct`                       | —                                                                      | creates or reuses active direct link                        | yes        |
| `sessions start --direct`                      | —                                                                      | creates direct link after session creation                  | yes        |
| `notify_stop` / `notify_input_request` fires   | removes one-shot listeners after delivery; persistent listeners remain | —                                                           | n/a        |
| `--close-link`                                 | —                                                                      | severs the active direct link for the (caller, target) pair | yes        |
| `sessions unsubscribe`                         | removes the listener if present                                        | severs the active direct link if present                    | yes        |
| caller session ends                            | removes all listeners registered by caller                             | severs all links the caller participates in                 | n/a        |

## Allowed values

### State matrix

| listener | link   | meaning                                                        | notification delivery                                                                           |
| -------- | ------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| none     | none   | caller has no subscription to target                           | none                                                                                            |
| present  | none   | caller passively watches target                                | active — `notify_stop` / `notify_input_request` deliver to caller's tmux                        |
| none     | active | caller is in 2-way conversation with target                    | none (suppressed by absence of listener)                                                        |
| present  | active | caller dispatched the target AND opened a conversation with it | **suppressed** — listener row remains, but notifications skip this caller until the link closes |

### Suppression rule (canonical)

While an active direct link exists for `(caller_session_id, target_session_id)`, all listener-driven notifications to that caller for events on that target are skipped. Notifications resume on the next event after the link is severed. The listener row is never mutated by link create / close.

Other listeners for the same target — registered by other callers — are unaffected by any link state.

### Interest semantics

The two axes encode distinct intents toward the target:

- A **listener** says "tell me when their state changes" — passive attention, expected while the caller is doing other work.
- A **direct link** says "I am the one talking to them now" — active attention, dominates while it is held.

A caller holding both has elected both: they spawned the target and want to be notified when it stops, AND they have opened a direct conversation with it. While the conversation is active, the active-attention channel supersedes the passive-attention channel — turn output flows through the direct link (cross-delivery), and the listener's stop notification would duplicate that signal. Once the conversation is closed, passive interest resumes.

This is the precise meaning of "suppression": the listener's interest is preserved, but its delivery is silenced while a stronger channel is active toward the same target.

## Known caveats

- **Listeners are persistent (DB-backed), not in-memory.** They survive daemon restart. The `session-listeners` design referred to in-memory storage in earlier revisions; the implementation has used SQLite for some time.
- **One-shot vs persistent listeners are distinct rows.** Both share the suppression rule. Both are removed by `unsubscribe`. One-shot listeners additionally self-remove on first notify.
- **`--close-link` and `unsubscribe` overlap on the link axis.** `--close-link` is convenient mid-conversation; `unsubscribe` is the umbrella verb that also clears the listener axis. Both severance paths leave the listener row intact except when `unsubscribe` is the verb used.
- **Idempotence of `unsubscribe`.** Empty state returns success. The response payload reports which (listener / link) was actually removed:
  ```
  { "status": "success",
    "listener_removed": bool,
    "link_closed":      bool,
    "link_id":          str | null }
  ```
- **Listener uniqueness.** At most one listener row exists per `(caller_session_id, target_session_id)` pair. Re-registration is a no-op when a row already exists.
- **Link uniqueness for direct mode.** At most one active `direct_link` exists per unordered `{caller, target}` pair. Repeat `--direct` sends against the same pair reuse the existing link.
- **Caller-session cleanup cascades to both axes.** Ending the caller session removes all listeners registered by it and severs all links it participates in, in a single cleanup pass.
- **Third-party link does not affect a caller's listener.** If session C holds a listener on target T, and session D opens a direct link with T, C's listener is unaffected (different caller). Suppression is scoped to the specific caller that holds both relationships.
- **Listener and link are independent records.** Creation, mutation, or destruction of one never touches the other. This is the canonical refutation of any code path that calls `unregister_listener` as part of link creation.
