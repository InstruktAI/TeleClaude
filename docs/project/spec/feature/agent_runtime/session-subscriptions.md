---
description: "Listener-based subscription/notification fan-out — sessions (and external subscribers) register interest in a target session's lifecycle events (stop, input-request) and receive notifications via host-pane injection. Excludes the bidirectional direct-conversation-link mechanism."
visibility: 'public'
---

# Session Subscriptions — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The listener mechanism by which one session (the **caller**) registers passive interest in another session (the **target**) and receives a one-shot notification when the target's turn finishes or when the target requests input. Listeners are durable records in the agent_runtime store, deduped by `(caller_session_id, target_session_id)`, and delivered to the caller's host pane via the shared host-pane delivery path. They are the asymmetric, passive channel — the caller wants to know "tell me when the target is done"; the target neither subscribes back nor sees who is listening.

This is distinct from — and intentionally separated from — the bidirectional **direct conversation link** mechanism. A direct link is a symmetric, peered conversation channel between two sessions; a listener is a one-way notification subscription. The unsubscribe surface (`telec sessions unsubscribe`) is the umbrella verb that severs BOTH for the caller against a target, but the two state planes are independent. While an active direct link exists between caller and target, listener notifications for that pair are suppressed at delivery time — the active conversation channel supersedes passive notification for the duration of the link, and the listener row is preserved for resumption after the link is severed. The direct-link mechanism gets its own spec.

## Canonical fields

### Use cases

#### Listener registration is per-caller deduped

```
Given an orchestrator session C dispatches a worker session T
When register-listener(target=T, caller=C, caller_host_pane=<C's host pane>, one_shot=False) is called
Then a listener record (target=T, caller=C, caller_host_pane=..., registered_at=<now>, one_shot=False) is inserted in the agent_runtime listener store
And if a record already exists for the (T, C) pair, the call is a no-op and reports "not new"
And on new registration, the call reports "new"
And the registry now reflects "C will be notified when T's turn ends"
```

#### Auto-registration on AI-to-AI start and AI-to-AI message

```
Given an AI-to-AI session start (initiator I dispatches child T)
When session-lifecycle creation runs and the listener-skip flag is false
Then register-listener(target=T, caller=I, caller_host_pane=I's host pane, one_shot=False) is invoked
And the listener persists across the lifetime of T

Given an AI sends a message to another session (caller C → target T) via the session-message entry
When the request is non-direct AND the caller's identity has a session id AND it differs from T AND the caller has a host pane
Then register-listener(target=T, caller=C, caller_host_pane=C's host pane, one_shot=True) is invoked
And C receives a single response notification on T's next stop, then the listener self-removes
```

#### What events trigger a notification

<!-- planned-change:detect-stalled-agent-startup -->

```
Given a target session T has registered listeners
When the agent coordinator detects T's agent-stop and calls notify-stop(T, computer, title)
Then a system message "Notification — Session T [on <computer>] [\"<title>\"] finished its turn. Use telec sessions tail T to inspect." is composed
And every active listener for T is iterated and delivered (subject to direct-link suppression below)
And per-target notification dedup: a notification-flag record gates duplicate stop notifications within the same turn (heartbeat-induced agent-stop events); cleared on the next real turn: any message typed into the session, including human input, orchestrator/integrator/peer/system dispatches, or TeleClaude Notification / Input Request / Linked output envelopes; not cleared by hook side-channel artifacts such as checkpoint Stop-hook feedback or CLI-internal `<system-reminder>`, `<task-notification>`, and `<hook_prompt>` wrappers

When the target session emits an input request and notify-input-request(T, computer, input_message) is called
Then a system message "Input Request — Session T on <computer> needs input: <input_message> Use telec sessions tail T to inspect, and Use telec sessions send T \"your response\" to respond." is composed and delivered to every active listener

Stop and input-request notifications are the ONLY two emitter functions
```

<!-- change:detect-stalled-agent-startup -->

```
Given a target session T has registered listeners
When the agent coordinator detects T's agent-stop and calls notify-stop(T, computer, title)
Then a system message "Notification — Session T [on <computer>] [\"<title>\"] finished its turn. Use telec sessions tail T to inspect." is composed
And every active listener for T is iterated and delivered (subject to direct-link suppression below)
And per-target notification dedup: a notification-flag record gates duplicate stop notifications within the same turn (heartbeat-induced agent-stop events); cleared on the next real turn: any message typed into the session, including human input, orchestrator/integrator/peer/system dispatches, or TeleClaude Notification / Input Request / Linked output envelopes; not cleared by hook side-channel artifacts such as checkpoint Stop-hook feedback or CLI-internal `<system-reminder>`, `<task-notification>`, and `<hook_prompt>` wrappers

When the target session emits an input request and notify-input-request(T, computer, input_message) is called
Then a system message "Input Request — Session T on <computer> needs input: <input_message> Use telec sessions tail T to inspect, and Use telec sessions send T \"your response\" to respond." is composed and delivered to every active listener

Stop, input-request, startup-check, and watch-wake notifications are the ONLY four emitter functions; startup-check and watch-wake deliver to the single watching caller (see the session-watch use cases below), not to the listener fan-out
```

<!-- /planned-change:detect-stalled-agent-startup -->

#### UC-SS1: Re-poke clears the per-turn dedup flag

```
Given target session T has a registered listener for caller session C
And C has already been notified once in T's current turn
When C re-pokes T via `telec sessions send` and the `[Orchestrator ...]` message is typed into T
And T finishes its next turn
Then T's `user_prompt_submit` for the orchestrator message is treated as a real turn
And the prompt event is enqueued for daemon processing
And T's per-target notification dedup flag is cleared
And `notify-stop(T)` delivers exactly one new stop notification to C for that completed turn
```

#### UC-SS2: Hook side-channel artifacts do not clear the dedup flag

```
Given target session T has its per-target notification dedup flag set for the current turn
When a checkpoint Stop-hook feedback prompt or a CLI-internal `<system-reminder>` artifact arrives at the hook receiver
Then the prompt artifact is dropped as a hook side-channel artifact
And no `user_prompt_submit` event is enqueued for daemon processing
And T's per-target notification dedup flag remains set
And no duplicate stop notification is delivered for the same turn
```

#### Notification delivery — direct-link suppression

```
Given a listener L for caller C on target T is about to be notified
When the notification fan-out iterates and reaches L
Then the active-link check for (C, T, mode="direct_link") runs
And if an active direct link exists between C and T, delivery is SKIPPED for L (listener record preserved)
And otherwise the listener-message delivery is invoked against C's host pane
And on successful host-pane delivery, the success counter is incremented and an info log is emitted
And on delivery failure, a warning is logged but no retry is attempted
And if the listener is one-shot, the record is removed after the delivery attempt (success or failure)
```

#### Per-pair serialization

```
Given concurrent operations against the same canonical pair (session_a, session_b)
When code paths require ordered access to the pair's link/listener state
Then a shared per-pair lock keyed by sorted (session_a, session_b) serializes them
And the lock is process-local
And the lock is used by direct-link creation/reuse to prevent duplicate-link races
And listener registration itself does NOT take this lock — uniqueness is enforced by the (target, caller) uniqueness constraint in the listener store
```

#### Pop-on-target-stop and caller cleanup

```
Given target session T has terminated
When session cleanup runs for T
Then pop-listeners(T) removes and returns every listener targeting T
And every popped listener record is gone (no further notification for T can occur — T is terminating)
And cleanup-caller-listeners(T) additionally removes every listener T itself had registered as a CALLER against other targets
And the link-cleanup step severs every conversation link involving T (direct-link mechanism, out of scope here)
```

#### Stale-listener health-check sweep

```
Given some listeners have been waiting longer than max_age_minutes (default 10)
When the stale-targets sweep is invoked periodically
Then it returns the unique target session ids with at least one listener registered before now - max_age_minutes
And for each returned target, the listener timestamps for that target are advanced to now
And the reset prevents the same target from appearing in the next sweep within max_age_minutes
And callers use the returned list to drive health checks on apparently-stuck targets (e.g., is the target session still alive?)
```

#### `telec sessions unsubscribe <session_id>` is the umbrella verb

```
Given a caller session C wants to stop caring about target T entirely
When the unsubscribe entry is invoked (identity=C, target=T)
Then unregister-listener(target=T, caller=C) removes the listener record if any
And the close-link-for-member path severs any active direct link involving (C, T)
And the response reports success with two boolean flags: whether a listener was removed, and whether a link was closed (plus the closed link id when applicable)
And the call is idempotent: empty state reports success with both action flags false
```

#### Read APIs

```
get-listeners(target) → listener list for one target
get-all-listeners() → mapping from target to listener list across all targets
get-listeners-for-caller(caller) → listener list for one caller
count-listeners() → total record count across all (target, caller) pairs
```

<!-- planned:detect-stalled-agent-startup -->

#### UC-SS3: AI-to-AI dispatch arms a one-shot startup check

```
Given an AI-to-AI session start (initiator I dispatches child T)
And the child creation carries I as `initiator_session_id` with the listener-skip flag false
When session-lifecycle creation runs on the computer that owns T — local or peer
Then a durable session watch (target=T, caller=I, kind=startup_check, fire_at=now+30s) is recorded on T's computer
And the watch is armed even when I's session row is not locally resolvable (remote dispatch via `--computer`) — the caller's delivery route is resolved at fire time, not at arm time
And no watch is armed when `initiator_session_id` is absent or the listener-skip flag is set
```

#### UC-SS4: Startup check fires on unresolved startup

```
Given a startup-check watch (target=T, caller=I) reaches its fire time
And T is not closed
And T has no recorded first agent activity (or its lifecycle status is still "initializing")
When the watch fires
Then one system notification is composed stating the facts (dispatch age, lifecycle status, absence of first agent activity) and that one observation is licensed
And the message names `telec sessions watch T --in <seconds>` as the way to keep monitoring genuine slow progress
And when I is local, delivery injects into I's host pane via the listener-message delivery path
And when I lives on another computer (T's origin names a peer initiator computer), the wake is forwarded to that computer over the same transport the stop-notification forwarding uses, and delivered to I's host pane there
And the watch row is removed on successful delivery
And the runtime performs no restart, no duplicate dispatch, and no health judgment — assessment stays with the caller
```

#### UC-SS5: Startup check expires silently once agent activity is observed

```
Given a startup-check watch (target=T, caller=I) reaches its fire time
And T has a recorded first agent activity timestamp
When the watch fires
Then the watch row is removed
And no notification is delivered — the normal stop-notification flow covers the rest of the turn
```

#### UC-SS6: `telec sessions watch` arms a heartbeat wake

```
Given a caller session C wants a future wake against a target session T
When C invokes `telec sessions watch T --in <seconds>` with a positive bounded duration
Then a durable session watch (target=T, caller=C, kind=heartbeat, fire_at=now+<seconds>) is recorded, replacing any existing watch for the (T, C) pair
And a non-positive or out-of-bounds duration is rejected at the API boundary with a typed validation error, and by the CLI before the request is sent
And when the watch fires, one wake notification with a factual status snapshot (derived agent status, lifecycle status, last-activity age) is delivered to C's host pane, and the row is removed on successful delivery
And the wake licenses exactly one observation; continued monitoring requires C to arm a new watch
And `telec sessions watch T --cancel` removes the pair's watch without firing
And a watch fires as a real wake event regardless of user intervention in C — C re-evaluates intent at wake time instead of monitoring being silently orphaned
```

#### UC-SS7: Watches survive daemon restart

```
Given durable watch rows exist when the daemon stops
When the daemon starts
Then every pending watch is re-armed from its stored fire time
And a watch whose fire time already passed fires promptly after startup
And a watch that had fired but whose delivery was not confirmed before the stop is re-armed and delivered again — duplicate wakes are tolerated, lost wakes are not
```

#### UC-SS8: Watch cleanup on termination and unsubscribe

```
Given a watch (target=T, caller=C) exists
When T terminates, or C terminates, or C invokes `telec sessions unsubscribe T`
Then the watch row is removed without firing
And the unsubscribe response's umbrella semantics cover listener, link, and watch state for the pair
```

#### UC-SS9: A failed wake delivery escalates, never disappears

```
Given a watch for caller C fires and its delivery attempt fails (pane injection error, forwarding transport error)
When the failure is observed
Then the watch row is retained and re-armed for a bounded number of short-delay redelivery attempts
And when redelivery succeeds, the row is removed and no further attempts occur
And when the attempt budget is exhausted, the row is removed and an operational event is emitted naming the caller, target, kind, and failure — the miss is observable, never silent
```

<!-- /planned:detect-stalled-agent-startup -->

### Cross-context references

- **identity** — listener registration is gated by caller identity binding (the caller's session id and host-pane reference from the caller identity). A request without a bound caller session (e.g., a TUI/tool client without identity headers) does not auto-register. The unsubscribe entry similarly resolves the caller from its clearance.
- **workflow** — orchestrator agents that dispatch worker sessions are the dominant producer of listener records: every AI-to-AI session start auto-registers a persistent (non-one-shot) listener so the orchestrator hears its workers' stop events. The orchestrator/worker coordination contract relies on this.
- **integration** — external messaging adapters are NOT a notification destination in the listener system. Notifications deliver exclusively via the listener-message path, which injects into the caller's host pane. Stop and input-request fan-out toward external adapters (Telegram, Discord, frontend) flows through separate agent-coordinator / adapter-client paths, not through listener records. The integration boundary is reached via the direct-link mechanism (out of scope) and the broader event-emission paths, not via listener notification.
- **Direct conversation link (separate spec)** — direct-link creation, member roles, per-link delivery cursors, severing semantics — the bidirectional peered-conversation channel between two (or more) sessions. While an active direct link covers a (caller, target) pair, listener notifications for that pair are suppressed at delivery time. The unsubscribe verb tears down both planes for the caller against the target. The direct-link contract is documented in its own snippet and intentionally NOT covered here.

## Known caveats

- **Dedup is per (target, caller) pair, not per target.** Multiple callers can listen to the same target; one caller can only listen to one target once. A second register call for the same pair is a no-op reporting "not new".
- **Notification dedup within a turn relies on a per-target flag.** The notify-stop path (via the agent-coordinator fan-out) consults a notification-flag record to suppress duplicate stop notifications when heartbeat-induced agent-stop events arrive within the same turn. The flag is cleared on the next real turn: any message typed into the session, including human input, orchestrator/integrator/peer/system dispatches, or TeleClaude Notification / Input Request / Linked output envelopes. Hook side-channel artifacts (checkpoint Stop-hook feedback and CLI-internal `<system-reminder>`, `<task-notification>`, and `<hook_prompt>` wrappers) are not turns and do not clear the flag. Without this gate, listeners would receive multiple "finished its turn" messages per actual turn.
- **One-shot listeners self-remove after delivery, persistent listeners do not.** AI-to-AI message sends register one-shot (single response expected). AI-to-AI session starts register persistent (orchestrator keeps hearing every stop until the worker terminates or the orchestrator unsubscribes/ends).
- **Direct-link suppression is delivery-time only — the listener record is preserved.** During an active direct link, listener notifications for the pair are silently skipped. The record stays so that notification resumes the next time the fan-out runs after the link has been severed. This intentionally keeps the two planes independent.
- **Delivery has no retry.** A failed listener delivery (the caller's host pane is gone, key injection errors out) is logged as a warning and dropped. The one-shot record is still removed on failure. The persistent record remains and will be retried only on the NEXT notification event.
- **Stale-target sweep is informational, not corrective.** It surfaces targets whose listeners have been waiting too long and resets timestamps to prevent re-surfacing. The sweep itself does not unregister listeners or terminate stuck targets — callers decide what to do with the list.
- **Storage is durable and survives service restart.** Listener records are durable across service restarts. A restart does not orphan listeners; they remain and the next stop/input-request emits as expected.
- **External (non-session) subscribers are not first-class.** The listener model assumes the caller is itself a session with a host pane reachable via the listener-message path. A purely external observer (e.g., a UI adapter wanting "tell me when session T stops") is not represented as a listener record — that fan-out lives in the agent-coordinator emit path, separate from this surface.
