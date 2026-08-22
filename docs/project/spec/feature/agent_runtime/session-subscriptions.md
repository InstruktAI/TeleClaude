---
description: Listener-based subscription/notification fan-out — sessions (and external
  subscribers) register interest in the lifecycle events this spec enumerates
  and receive notifications via host-pane injection. Excludes the bidirectional direct-conversation-link
  mechanism.
visibility: public
---

# Session Subscriptions — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

<!-- planned-change:envelope-authoritative-classification -->
The listener mechanism by which one session (the **caller**) registers passive interest in another session (the **target**) and receives a one-shot notification when the target's turn finishes or when the target requests input. Listeners are durable records in the agent_runtime store, deduped by `(caller_session_id, target_session_id)`, and delivered to the caller's host pane via the shared host-pane delivery path. They are the asymmetric, passive channel — the caller wants to know "tell me when the target is done"; the target neither subscribes back nor sees who is listening.
<!-- change:envelope-authoritative-classification -->
The listener mechanism by which one session (the **caller**) registers passive interest in another session (the **target**) and receives a notification when the target's turn finishes. Listeners are durable records in the agent_runtime store, deduped by `(caller_session_id, target_session_id)`, and delivered to the caller's host pane via the shared host-pane delivery path. They are the asymmetric, passive channel — the caller wants to know "tell me when the target is done"; the target neither subscribes back nor sees who is listening.
<!-- /planned-change:envelope-authoritative-classification -->

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

```
Given a target session T has registered listeners
When the agent coordinator detects T's agent-stop and calls notify-stop(T, computer, title)
Then a system message "Notification — Session T [on <computer>] [\"<title>\"] finished its turn. Use telec sessions tail T to inspect." is composed
And every active listener for T is iterated and delivered (subject to direct-link suppression below)
<!-- planned-change:envelope-authoritative-classification -->
And per-target notification dedup: a notification-flag record gates duplicate agent-stop notifications within the same turn; cleared on the next real turn: any message typed into the session, including human input, orchestrator/integrator/peer/system dispatches, or TeleClaude Notification / Input Request / Linked output envelopes; not cleared by hook side-channel artifacts such as checkpoint Stop-hook feedback or CLI-internal `<system-reminder>`, `<task-notification>`, and `<hook_prompt>` wrappers
<!-- change:envelope-authoritative-classification -->
And per-target notification dedup: a notification-flag record gates duplicate agent-stop notifications within the same turn; it is cleared by the next accepted native user entry that the runtime normalizer classifies as a real turn, including prompt input and complete registered platform or identity envelopes, but not by declared runtime side-channel artifacts
<!-- /planned-change:envelope-authoritative-classification -->

<!-- planned-change:envelope-authoritative-classification -->
When the target session emits an input request and notify-input-request(T, computer, input_message) is called
Then a system message "Input Request — Session T on <computer> needs input: <input_message> Use telec sessions tail T to inspect, and Use telec sessions send T \"your response\" to respond." is composed and delivered to every active listener
<!-- change:envelope-authoritative-classification -->
<!-- /planned-change:envelope-authoritative-classification -->

<!-- planned-change:session-distress-ingestion -->
The fan-out emits exactly the notification kinds this spec's use cases enumerate
<!-- change:session-distress-ingestion -->
The fan-out emits exactly the notification kinds this spec's use cases enumerate
<!-- /planned-change:session-distress-ingestion -->
```

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

#### UC-SS3: A cross-machine initiator is notified when its dispatched session stops

```
Given an initiator session I running on computer A dispatches session T to computer B
And T's session record on B carries both I's session id and I's computer name
When T's agent stop is detected on B
Then B forwards a stop notification for T to A, naming B as the source computer
And A raises the stop event for T and delivers the notification to I through its local fan-out
And I is notified without having polled for T's completion

Given a session record carries an initiator session id but no initiator computer
When that session's agent stop is detected
Then no cross-machine forward is attempted
And the omission is recorded as a diagnostic naming the session and its initiator, rather than passing silently
```

<!-- planned:session-distress-ingestion -->
#### UC-SS4: A subscribed caller hears that its session is stuck or broken

```gherkin
Given a caller is subscribed to a target session's lifecycle events
When the target session becomes blocked waiting on a permission approval
Or the target session's turn ends because of a runtime or provider failure
Then the platform ingests the distress signal as a typed event naming its kind
And the subscribed caller receives a notification naming the target session and the distress kind
And the caller is not left to infer distress from silence or transcript polling
```
<!-- /planned:session-distress-ingestion -->

<!-- planned:session-distress-ingestion -->
#### UC-SS5: Distress kinds vary by agent runtime without changing the caller contract

```gherkin
Given target sessions run on different agent runtimes with different native distress signals
When each runtime surfaces the distress states it natively exposes
Then every ingested state maps to the platform's typed distress vocabulary
And a runtime exposing no signal for a distress kind simply never produces that kind
And the subscribed caller consumes one vocabulary regardless of the target's runtime
```
<!-- /planned:session-distress-ingestion -->

<!-- planned:session-distress-ingestion -->
#### UC-SS6: A turn that died of a failure is not reported to the caller as a completion

```gherkin
Given a caller is subscribed to a target session
When the target session's turn is terminated by a runtime or provider failure
Then the notification the caller receives for that turn names the failure
And the caller does not receive a clean turn-end notification as the account of that turn
```
<!-- /planned:session-distress-ingestion -->

<!-- planned:session-distress-ingestion -->
#### UC-SS7: Distress reaches a caller subscribed across a computer boundary

```gherkin
Given a caller on one computer is subscribed to a target session running on another
When the target session enters a distress state
Then the caller receives the same distress notification it would receive for a target on its own computer
And the notification names the computer the target runs on
```
<!-- /planned:session-distress-ingestion -->

<!-- planned:session-distress-ingestion -->
#### UC-SS8: An active direct conversation link does not withhold distress

```gherkin
Given a caller and a target session are covered by an active direct conversation link
And turn-end notifications for that pair are suppressed for the duration of the link
When the target session enters a distress state
Then the caller still receives the distress notification for that target
And the suppression of turn-end notifications for the pair is unchanged
```
<!-- /planned:session-distress-ingestion -->

<!-- planned:envelope-authoritative-classification -->
#### UC-SS9: A notification names a computer only when the target is elsewhere

```gherkin
Given a listener receives a notification about a target session
When the target runs on the same computer as the listener
Then the notification names no computer and its suggested commands carry no computer selector
When the target runs on a different computer
Then the notification names that computer and every suggested command carries the matching computer selector
```

<!-- /planned:envelope-authoritative-classification -->

### Cross-context references

- **identity** — listener registration is gated by caller identity binding (the caller's session id and host-pane reference from the caller identity). A request without a bound caller session (e.g., a TUI/tool client without identity headers) does not auto-register. The unsubscribe entry similarly resolves the caller from its clearance.
- **workflow** — orchestrator agents that dispatch worker sessions are the dominant producer of listener records: every AI-to-AI session start auto-registers a persistent (non-one-shot) listener so the orchestrator hears its workers' stop events. The orchestrator/worker coordination contract relies on this.
<!-- planned-change:envelope-authoritative-classification -->
- **integration** — external messaging adapters are NOT a notification destination in the listener system. Notifications deliver exclusively via the listener-message path, which injects into the caller's host pane. Stop and input-request fan-out toward external adapters (Telegram, Discord, frontend) flows through separate agent-coordinator / adapter-client paths, not through listener records. The integration boundary is reached via the direct-link mechanism (out of scope) and the broader event-emission paths, not via listener notification.
<!-- change:envelope-authoritative-classification -->
- **integration** — external messaging adapters are NOT a notification destination in the listener system. Notifications deliver exclusively via the listener-message path, which injects into the caller's host pane. Stop fan-out toward external adapters (Telegram, Discord, frontend) flows through separate agent-coordinator / adapter-client paths, not through listener records. The integration boundary is reached via the direct-link mechanism (out of scope) and the broader event-emission paths, not via listener notification.
<!-- /planned-change:envelope-authoritative-classification -->
- **Direct conversation link (separate spec)** — direct-link creation, member roles, per-link delivery cursors, severing semantics — the bidirectional peered-conversation channel between two (or more) sessions. While an active direct link covers a (caller, target) pair, listener notifications for that pair are suppressed at delivery time. The unsubscribe verb tears down both planes for the caller against the target. The direct-link contract is documented in its own snippet and intentionally NOT covered here.

## Known caveats

- **Dedup is per (target, caller) pair, not per target.** Multiple callers can listen to the same target; one caller can only listen to one target once. A second register call for the same pair is a no-op reporting "not new".
<!-- planned-change:envelope-authoritative-classification -->
- **Notification dedup within a turn relies on a per-target flag.** The notify-stop path (via the agent-coordinator fan-out) consults a notification-flag record to suppress duplicate agent-stop notifications within the same turn. The flag is cleared on the next real turn: any message typed into the session, including human input, orchestrator/integrator/peer/system dispatches, or TeleClaude Notification / Input Request / Linked output envelopes. Hook side-channel artifacts (checkpoint Stop-hook feedback and CLI-internal `<system-reminder>`, `<task-notification>`, and `<hook_prompt>` wrappers) are not turns and do not clear the flag. Without this gate, listeners would receive multiple "finished its turn" messages per actual turn.
<!-- change:envelope-authoritative-classification -->
- **Notification dedup within a turn relies on a per-target flag.** The notify-stop path (via the agent-coordinator fan-out) consults a notification-flag record to suppress duplicate agent-stop notifications within the same turn. The next accepted native user entry clears the flag only when the runtime normalizer classifies it as a real turn; declared runtime side-channel artifacts do not. Without this gate, listeners would receive multiple "finished its turn" messages per actual turn.
<!-- /planned-change:envelope-authoritative-classification -->
- **One-shot listeners self-remove after delivery, persistent listeners do not.** AI-to-AI message sends register one-shot (single response expected). AI-to-AI session starts register persistent (orchestrator keeps hearing every stop until the worker terminates or the orchestrator unsubscribes/ends).
- **Direct-link suppression is delivery-time only — the listener record is preserved.** During an active direct link, listener notifications for the pair are silently skipped. The record stays so that notification resumes the next time the fan-out runs after the link has been severed. This intentionally keeps the two planes independent.
- **Delivery has no retry.** A failed listener delivery (the caller's host pane is gone, key injection errors out) is logged as a warning and dropped. The one-shot record is still removed on failure. The persistent record remains and will be retried only on the NEXT notification event.
- **Stale-target sweep is informational, not corrective.** It surfaces targets whose listeners have been waiting too long and resets timestamps to prevent re-surfacing. The sweep itself does not unregister listeners or terminate stuck targets — callers decide what to do with the list.
<!-- planned-change:envelope-authoritative-classification -->
- **Storage is durable and survives service restart.** Listener records are durable across service restarts. A restart does not orphan listeners; they remain and the next stop/input-request emits as expected.
<!-- change:envelope-authoritative-classification -->
- **Storage is durable and survives service restart.** Listener records are durable across service restarts. A restart does not orphan listeners; they remain and the next stop emits as expected.
<!-- /planned-change:envelope-authoritative-classification -->
- **External (non-session) subscribers are not first-class.** The listener model assumes the caller is itself a session with a host pane reachable via the listener-message path. A purely external observer (e.g., a UI adapter wanting "tell me when session T stops") is not represented as a listener record — that fan-out lives in the agent-coordinator emit path, separate from this surface.
