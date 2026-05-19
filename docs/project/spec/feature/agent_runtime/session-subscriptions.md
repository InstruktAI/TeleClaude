---
id: 'project/spec/feature/agent_runtime/session-subscriptions'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'v1 listener-based subscription/notification fan-out — sessions (and external subscribers) register interest in a target session''s lifecycle events (stop, input-request) and receive notifications via tmux injection. Excludes the bidirectional direct-conversation-link mechanism.'
---

# Session Subscriptions — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The v1 listener mechanism by which one session (the **caller**) registers passive interest in another session (the **target**) and receives a one-shot notification when the target's turn finishes (`notify_stop`) or when the target requests input (`notify_input_request`). Listeners are durable rows in the agent_runtime SQLite store, deduped by `(caller_session_id, target_session_id)`, and delivered to the caller's tmux pane via the shared tmux delivery path. They are the asymmetric, passive channel — the caller wants to know "tell me when the target is done"; the target neither subscribes back nor sees who is listening.

This is distinct from — and intentionally separated from — the bidirectional **direct conversation link** mechanism that lives in the same module (`create_or_reuse_direct_link`, `close_link_for_member`, etc.). A direct link is a symmetric, peered conversation channel between two sessions; a listener is a one-way notification subscription. The unsubscribe surface (`telec sessions unsubscribe`) is the umbrella verb that severs BOTH for the caller against a target, but the two state planes are independent. While an active direct link exists between caller and target, listener notifications for that pair are suppressed at delivery time — the active conversation channel supersedes passive notification for the duration of the link, and the listener row is preserved for resumption after the link is severed. The direct-link mechanism gets its own spec.

## Canonical fields

### Behavioral contract

#### Listener registration is per-caller deduped

```
Given an orchestrator session C dispatches a worker session T
When register_listener(target_session_id=T, caller_session_id=C, caller_tmux_session=<C's tmux name>, one_shot=False) is called
Then a row (target_session_id=T, caller_session_id=C, caller_tmux_session=..., registered_at=<now>, one_shot=False) is inserted in the SQLite listener table
And if a row already exists for the (T, C) pair, the call is a no-op and returns False
And on new registration, the call returns True
And the registry now reflects "C will be notified when T's turn ends"
```

#### Auto-registration on AI-to-AI start and AI-to-AI message

```
Given an AI-to-AI session start (initiator I dispatches child T)
When session_lifecycle creation runs and cmd.skip_listener_registration is false
Then register_listener(target_session_id=T, caller_session_id=I, caller_tmux_session=I.tmux_session_name, one_shot=False) is invoked
And the listener persists across the lifetime of T

Given an AI sends a message to another session (caller C → target T) via the sessions message endpoint
When the request is non-direct AND identity.session_id is set AND identity.session_id != T AND identity.tmux_session_name is set
Then register_listener(target_session_id=T, caller_session_id=C, caller_tmux_session=C's tmux, one_shot=True) is invoked
And C receives a single response notification on T's next stop, then the listener self-removes
```

#### What events trigger a notification

```
Given a target session T has registered listeners
When agent_coordinator detects T's agent_stop and calls notify_stop(T, computer, title)
Then a system message "Notification — Session T [on <computer>] [\"<title>\"] finished its turn. Use telec sessions tail T to inspect." is composed
And every active listener for T is iterated and delivered (subject to direct-link suppression below)
And per-target notification dedup: a notification_flag row gates duplicate stop notifications within the same turn (heartbeat-induced agent_stop events); cleared on the next user prompt

When the target session emits an input request and notify_input_request(T, computer, input_message) is called
Then a system message "Input Request — Session T on <computer> needs input: <input_message> Use telec sessions tail T to inspect, and Use telec sessions send T \"your response\" to respond." is composed and delivered to every active listener

Stop and input-request notifications are the ONLY two emitter functions in v1
```

#### Notification delivery — direct-link suppression

```
Given a listener L for caller C on target T is about to be notified
When _notify_listeners(T, message) iterates and reaches L
Then db.get_active_link_between_sessions(C, T, mode="direct_link") is queried
And if an active direct link exists between C and T, delivery is SKIPPED for L (listener row preserved)
And otherwise deliver_listener_message(C, C.tmux_session, message) is invoked
And on successful tmux delivery, success_count is incremented and an info log is emitted
And on delivery failure, a warning is logged but no retry is attempted in v1
And if the listener is one_shot, the row is removed after the delivery attempt (success or failure)
```

#### Per-pair serialization

```
Given concurrent operations against the same canonical pair (session_a, session_b)
When code paths require ordered access to the pair's link/listener state
Then _get_pair_lock(session_a, session_b) returns a shared asyncio.Lock keyed by tuple(sorted((session_a, session_b)))
And the lock instance lives in process-local _PAIR_LOCKS guarded by _PAIR_LOCKS_GUARD
And the lock is used by direct-link creation/reuse to prevent duplicate-link races
And listener registration itself does NOT take this lock — uniqueness is enforced by the SQLite (target_session_id, caller_session_id) primary key in db.register_listener
```

#### Pop-on-target-stop and caller cleanup

```
Given target session T has terminated
When session_cleanup runs for T
Then pop_listeners(T) removes and returns every listener targeting T
And every popped listener row is gone (no further notification for T can occur — T is terminating)
And cleanup_caller_listeners(T) additionally removes every listener T itself had registered as a CALLER against other targets
And cleanup_session_links(T) severs every conversation link involving T (direct-link mechanism, out of scope here)
```

#### Stale-listener health-check sweep

```
Given some listeners have been waiting longer than max_age_minutes (default 10)
When get_stale_targets(max_age_minutes) is invoked periodically
Then db.get_stale_listener_targets(threshold_iso) returns the unique target_session_ids with at least one listener registered_at < now - max_age_minutes
And for each returned target, db.reset_listener_timestamps(target_id, now_iso) advances the registered_at timestamp
And the reset prevents the same target from appearing in the next sweep within max_age_minutes
And callers use the returned list to drive health checks on apparently-stuck targets (e.g., is the target session still alive?)
```

#### `telec sessions unsubscribe <session_id>` is the umbrella verb

```
Given a caller session C wants to stop caring about target T entirely
When POST /sessions/{T}/unsubscribe is hit (identity=C)
Then unregister_listener(target_session_id=T, caller_session_id=C) removes the listener row if any
And close_link_for_member(caller_session_id=C, target_session_id=T) severs any active direct link involving (C, T)
And the response is { status: "success", listener_removed: <bool>, link_closed: <bool>, link_id: <string|null> }
And the call is idempotent: empty state returns status=success with both action flags false
```

#### Read APIs

```
get_listeners(target_session_id) → SessionListener[] for one target
get_all_listeners() → dict[target_session_id, SessionListener[]] across all targets
get_listeners_for_caller(caller_session_id) → SessionListener[] for one caller
count_listeners() → total row count across all (target, caller) pairs
```

### Implementation pointers (v1)

- Listener API surface: `teleclaude/core/session_listeners.py:117` (`register_listener`), `:166` (`unregister_listener`), `:195` (`get_listeners`), `:210` (`pop_listeners`), `:243` (`cleanup_caller_listeners`), `:264` (`get_all_listeners`), `:280` (`get_listeners_for_caller`), `:295` (`count_listeners`), `:300` (`get_stale_targets`)
- Notification emitters: `teleclaude/core/session_listeners.py:330` (`_notify_listeners` — includes direct-link suppression), `:395` (`notify_stop`), `:420` (`notify_input_request`)
- Per-pair lock primitive: `teleclaude/core/session_listeners.py:26` (`_PAIR_LOCKS` / `_PAIR_LOCKS_GUARD`), `:68` (`_get_pair_lock`)
- Auto-registration call sites: `teleclaude/core/command_handlers/_session.py:225` (one_shot=False on AI-to-AI session start), `teleclaude/api/sessions_routes.py:962` (one_shot=True on AI-to-AI message send)
- Stop fan-out: `teleclaude/core/agent_coordinator/_fanout.py:119` (`notify_stop` called from the agent_stop fan-out path, gated by the per-turn notification flag)
- Cleanup integration: `teleclaude/core/session_cleanup.py:28` import, `:172` (`pop_listeners(session_id)`), `:181` (`cleanup_caller_listeners(session_id)`)
- HTTP umbrella verb: `teleclaude/api/sessions_actions_routes.py:676` (`@router.post("/sessions/{session_id}/unsubscribe")`)
- CLI surface: `telec sessions unsubscribe <session_id>` — see `teleclaude/cli/telec.py` `CLI_SURFACE`
- Delivery primitive: `teleclaude/core/tmux_delivery.py:27` (`deliver_listener_message`)
- Persistence: `teleclaude/core/db/_listeners.py:23` (`register_listener`), `:61` (`unregister_listener`), `:80` (`pop_listeners_for_target`), `:92` (`cleanup_caller_listeners`) — SQLite-backed for daemon-restart durability

### Cross-context references

- **identity** — listener registration is gated by caller identity binding (`identity.session_id`, `identity.tmux_session_name` from `CallerIdentity`). A request without a bound caller session (e.g., a TUI/tool client without identity headers) does not auto-register. The unsubscribe endpoint similarly resolves the caller from `clearance_sessions_unsubscribe`.
- **workflow** — orchestrator agents that dispatch worker sessions are the dominant producer of listener rows: every AI-to-AI session start auto-registers a persistent (non-one-shot) listener so the orchestrator hears its workers' stop events. The orchestrator/worker coordination contract relies on this.
- **integration** — external messaging adapters are NOT a notification destination in the listener system. `_notify_listeners` delivers exclusively via `deliver_listener_message`, which injects into the caller's tmux pane. Stop and input-request fan-out toward external adapters (Telegram, Discord, frontend) flows through separate agent_coordinator / adapter_client paths, not through listener rows. The integration boundary is reached via the direct-link mechanism (out of scope) and the broader event emission paths, not via listener notification.
- **Direct conversation link (same module, separate spec)** — `create_or_reuse_direct_link`, `close_link`, `close_link_for_member`, `add_link_member`, `get_active_links_for_session`, `resolve_link_for_sender_target`, `cleanup_session_links` form the bidirectional peered-conversation channel between two (or more) sessions. While an active direct link covers a (caller, target) pair, listener notifications for that pair are suppressed at delivery time. The unsubscribe verb tears down both planes for the caller against the target. The direct-link contract — link creation, member roles, per-link delivery cursors, severing semantics — is documented in its own snippet and intentionally NOT covered here.

## Known caveats

- **Dedup is per (target, caller) pair, not per target.** Multiple callers can listen to the same target; one caller can only listen to one target once. A second register call for the same pair is a no-op returning False.
- **Notification dedup within a turn relies on a per-target flag.** `notify_stop` (via the agent_coordinator fan-out) consults a `notification_flag` row to suppress duplicate stop notifications when heartbeat-induced agent_stop events arrive within the same turn. The flag is cleared on the next user prompt. Without this gate, listeners would receive multiple "finished its turn" messages per actual turn.
- **One-shot listeners self-remove after delivery, persistent listeners do not.** AI-to-AI message sends register one_shot=True (single response expected). AI-to-AI session starts register one_shot=False (orchestrator keeps hearing every stop until the worker terminates or the orchestrator unsubscribes/ends).
- **Direct-link suppression is delivery-time only — the listener row is preserved.** During an active direct link, listener notifications for the pair are silently skipped. The row stays so that notification resumes the next time `_notify_listeners` runs after the link has been severed. This intentionally keeps the two planes independent.
- **Delivery has no retry.** A failed `deliver_listener_message` (the caller's tmux pane is gone, send-keys errors out) is logged as a warning and dropped. The one-shot row is still removed on failure. The persistent row remains and will be retried only on the NEXT notification event.
- **Stale-target sweep is informational, not corrective.** `get_stale_targets` surfaces targets whose listeners have been waiting too long and resets timestamps to prevent re-surfacing. The sweep itself does not unregister listeners or terminate stuck targets — callers decide what to do with the list.
- **Storage is SQLite-backed and survives daemon restart.** Listener rows are durable across daemon restarts. A restart does not orphan listeners; they remain and the next stop/input-request emits as expected.
- **External (non-session) subscribers are not first-class.** The listener model assumes the caller is itself a session with a tmux pane reachable via `deliver_listener_message`. A purely external observer (e.g., a UI adapter wanting "tell me when session T stops") is not represented as a listener row — that fan-out lives in the agent_coordinator emit path, separate from this surface.
