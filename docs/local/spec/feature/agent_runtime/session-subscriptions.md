---
description: Passive session subscriptions and parent-attention fan-out through semantic
  control delivery, separate from direct conversation links.
visibility: public
---

# Session Subscriptions — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The listener mechanism by which one session (the **caller**) registers passive
interest in another session (the **target**). Listeners are durable records in
the agent_runtime store, unique per caller-target pair. Notifications are
semantic control payloads handed to the control-delivery surface. They are an
asymmetric, passive channel: the target neither subscribes back nor sees who
is listening. The use cases below define which observations reach each audience.
Turn-end notices are deduplicated per target, caller, and target turn: an
accepted new input from the caller opens one new notice opportunity, while
hook-side feedback and internal reminders neither reopen it nor create a
duplicate notice.

This is distinct from — and intentionally separated from — the bidirectional **direct conversation link** mechanism. A direct link is a symmetric, peered conversation channel between two sessions; a listener is a one-way notification subscription. The unsubscribe surface (`telec sessions unsubscribe`) is the umbrella verb that severs BOTH for the caller against a target, but the two state planes are independent. While an active direct link exists between caller and target, turn-end notifications for that pair are suppressed at delivery time — the active conversation channel supersedes passive notification for the duration of the link, and the listener row is preserved for resumption after the link is severed. Distress notifications are not suppressed. The direct-link mechanism gets its own spec.

## Canonical fields

### Use cases

#### UC-SS18: Notification observation and outcome semantics

```
Given an agent session watches a target session
When the target finishes its turn, fails its turn, or waits for approval or input
Then the watching agent receives the corresponding observation under the audience rules in this spec
And terminal outcomes retain their shared per-turn outcome slot
And nonterminal attention preserves distinct source occurrences through the existing delivery boundary
And a runtime signal the platform admits into none of those states reaches no audience at all
```

#### UC-SS1: A caller receives one completion notice for each new target turn

```
Scenario: A new turn is reported after the caller sends input
  Given caller C has already received a completion notice for target T's previous turn
  When C sends new input to T and T completes its next turn
  Then C receives exactly one completion notice for that new turn
```

#### UC-SS2: Hook side-channel artifacts do not clear the dedup flag

#### UC-SS11: A caller in a live conversation with its target is not also sent that target's turn-end notice

```
Given a subscribed agent session is in a live conversation with the target it subscribed to
When that target finishes a turn
Then the subscribing session is not sent a separate turn-end notification for it
And its subscription survives, so it is notified again once the conversation ends
```

#### UC-SS13: A subscribing agent hears when its target finishes

```gherkin
Given a subscribed agent session holds no live conversation with the target it subscribed to
When that target finishes a turn
Then the subscribing session is notified that the turn finished
And a subscription registered for a single reply is spent by that notification, whether or not it arrived
```

#### UC-SS19: A caller can tell when its target ended a turn with no content

```gherkin
Given a subscribed agent session holds no live conversation with the target it subscribed to
When that target finishes a turn whose entire authored output, read when the turn stops, is `NOOP`
Then the subscribing session is notified that the turn finished
And the notification states that the turn ended with `NOOP`
And the notification carries no instruction to inspect the target
And a subscription registered for a single reply is spent by that notification

Given a subscribed agent session holds no live conversation with the target it subscribed to
When that target finishes a turn with any other authored output, or one not yet readable when the turn stops
Then the subscribing session is notified when the turn stops
And the notification carries the instruction to inspect the target
```

#### UC-SS12: A supervisor receives distress only when its notification is accepted

```gherkin
Given an agent session is persistently subscribed to a target session, or dispatched it from another computer
When the target session enters a distress state
Then that session is a member of the distress audience for the event
And an agent session subscribed only for a single reply is not a member, and its subscription is left unspent
And a member counts as having been reached only when the distress notification is accepted by it
```

#### UC-SS21: A person can stop their agent's connection to a target

```
Given a person wants their agent to stop following a target and close any direct conversation with it
When their agent invokes `telec sessions unsubscribe` for that target
Then the listener is removed and any active direct link is closed
And the result reports which actions were taken, including the closed link id when applicable
And repeating the request succeeds without changing state again
```

#### Read APIs

```
get-listeners(target) → listener list for one target
get-all-listeners() → mapping from target to listener list across all targets
get-listeners-for-caller(caller) → listener list for one caller
count-listeners() → total record count across all (target, caller) pairs
```

#### UC-SS3: A remote initiator learns when its dispatched session stops

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

#### UC-SS4: A subscribed caller hears that its session is stuck or broken

```gherkin
Given a caller is subscribed to a target session's lifecycle events
When the target session becomes blocked waiting on a permission approval
Or input for the target session waits because delivery cannot identify its composer
Or the target session's turn ends because of a runtime or provider failure
Then the platform ingests the distress signal as a typed event naming its kind
And the subscribed caller receives a notification naming the target session and the distress kind
And a blocked notification raised by delivery carries a capture of the target's pane
And the caller is not left to infer distress from silence or transcript polling
```

#### UC-SS20: A caller can learn that its target may not have received startup input

```gherkin
Given an agent session watches a target session
And the target's startup ended with an uncertain-delivery outcome because the agent_runtime service was replaced while submitting its first startup input
When the replacement service records that outcome
Then the outcome is delivered as a distress notification under the audience rules of this spec
And the notification names the target session and states that its first startup input may not have reached the target's agent and was not submitted again
And it carries an actionable way to inspect the target's terminal state
And it is delivered once, and the target's later turn notifications are delivered as they would be without it
```

#### UC-SS5: Distress kinds vary by agent runtime without changing the caller contract

```gherkin
Given target sessions run on different agent runtimes with different native distress signals
When each runtime surfaces the distress states it natively exposes
Then every ingested state maps to the platform's typed distress vocabulary
And a runtime exposing no native signal for a distress kind produces that kind only from the platform's own observation
And delivery finding no identifiable composer produces the blocked kind on every runtime
And the subscribed caller consumes one vocabulary regardless of the target's runtime
```

#### UC-SS6: A turn that died of a failure is not reported to the caller as a completion

```gherkin
Given a caller is subscribed to a target session
When the target session's turn is terminated by a runtime or provider failure
Then the notification the caller receives for that turn names the failure
And the caller does not receive a clean turn-end notification as the account of that turn
```

#### UC-SS7: Distress reaches a caller subscribed across a computer boundary

```gherkin
Given a caller on one computer is subscribed to a target session running on another
When the target session enters a distress state
Then the caller receives the same distress notification it would receive for a target on its own computer
```

#### UC-SS8: An active direct conversation link does not withhold distress

```gherkin
Given a caller and a target session are covered by an active direct conversation link
And turn-end notifications for that pair are suppressed for the duration of the link
When the target session enters a distress state
Then the caller still receives the distress notification for that target
And the suppression of turn-end notifications for the pair is unchanged
```

#### UC-SS9: A caller gets usable commands for a local or remote target

```gherkin
Given a listener receives a notification about a target session
When the target runs on the same computer as the listener
Then the notification names no computer and its suggested commands carry no computer selector
When the target runs on a different computer
Then the notification names that computer and every suggested command carries the matching computer selector
```

#### UC-SS10: Distress reaches the human or supervisor on the right surface

```gherkin
Given a target session has no live persistent supervising caller
When the target reports a native failure or approval wait
Then its existing human-facing distress notice is delivered
And a platform silence observation produces no human-facing fallback
When the target has a live persistent supervising caller
Then its distress notification is delivered to its supervising caller through agent control delivery
And the target's human-facing channel receives nothing from that mechanism
```

#### UC-SS14

#### UC-SS15: A parent can assess a child's attention from the evidence provided

```gherkin
Given a parent agent receives an approval-wait or failure observation about its child
When the platform presents the observation
Then it identifies the child, the originating runtime, the observation time, and the available native details
And it provides an actionable way to inspect the child's current terminal state independently of its transcript
And it directs the parent to assess current evidence and act within its existing mandate
And the event itself grants no additional permission or authority
```

#### UC-SS16: Distinct attention occurrences remain observable within one turn

```gherkin
Given a parent agent has received an attention observation about its child
When the child produces a distinct approval-wait observation before ending the same turn
Then the parent receives the distinct observation through the existing control-delivery boundary
And sharing a kind or unresolved condition does not suppress that observation
And the consumer adds no separate acknowledgement, retry, or duplicate-detection mechanism
```

#### UC-SS17

### Cross-context references

- **supervisory silence** — `local/projects/teleclaude/spec/feature/agent_runtime/supervisory-silence-observations` owns caller-only missing-signal observations and their assessment boundary.

- **identity** — listener registration is gated by caller identity binding (the caller's session id and host-pane reference from the caller identity). A request without a bound caller session (e.g., a TUI/tool client without identity headers) does not auto-register. The unsubscribe entry similarly resolves the caller from its clearance.
- **workflow** — orchestrator agents that dispatch worker sessions are the dominant producer of listener records: every AI-to-AI session start auto-registers a persistent (non-one-shot) listener so the orchestrator hears its workers' stop events. The orchestrator/worker coordination contract relies on this.
- **integration** — external messaging adapters are NOT a notification destination in the listener system. Notifications deliver exclusively via the listener-message path, which injects into the caller's host pane. Stop fan-out toward external adapters (Telegram, Discord, frontend) flows through separate agent-coordinator / adapter-client paths, not through listener records. The integration boundary is reached via the direct-link mechanism (out of scope) and the broader event-emission paths, not via listener notification.
- **Direct conversation link (separate spec)** — direct-link creation, member roles, per-link delivery cursors, severing semantics — the bidirectional peered-conversation channel between two (or more) sessions. While an active direct link covers a (caller, target) pair, turn-end notifications for that pair are suppressed at delivery time and distress notifications are not. The unsubscribe verb tears down both planes for the caller against the target. The direct-link contract is documented in its own snippet and intentionally NOT covered here.

## Known caveats

- **Dedup is per (target, caller) pair, not per target.** Multiple callers can listen to the same target; one caller can only listen to one target once. A second register call for the same pair is a no-op reporting "not new".
- **Terminal outcomes and attention occurrences are distinct.** Turn-end and
  turn-failure retain their shared terminal-outcome slot. Nonterminal attention
  retains source-occurrence identity through the existing delivery boundary;
  the fan-out does not collapse separate observations by kind, turn, or an
  inferred unresolved condition. Consumers rely on control delivery rather
  than adding their own acknowledgement, retry, or duplicate-detection layer.
- **One-shot listeners self-remove after delivery, persistent listeners do not.** AI-to-AI message sends register one-shot (single response expected). AI-to-AI session starts register persistent (orchestrator keeps hearing every stop until the worker terminates or the orchestrator unsubscribes/ends).
- **Direct-link suppression is delivery-time only, applies to turn-end only, and the listener record is preserved.** During an active direct link, turn-end notifications for the pair are silently skipped; distress notifications are delivered regardless, because the live channel carries no output for a stuck or dead target. The record stays so that turn-end notification resumes the next time the fan-out runs after the link has been severed. This intentionally keeps the two planes independent.
- **Delivery has no retry.** A failed listener delivery (the caller's host pane is gone, key injection errors out) is logged as a warning and dropped. The one-shot record is still removed on failure. The persistent record remains and will be retried only on the NEXT notification event.
- **Stale-target sweep is informational, not corrective.** It surfaces targets whose listeners have been waiting too long and resets timestamps to prevent re-surfacing. The sweep itself does not unregister listeners or terminate stuck targets — callers decide what to do with the list.
- **Storage is durable and survives service restart.** Listener records are durable across service restarts. A restart does not orphan listeners; they remain and the next stop emits as expected.
- **External (non-session) subscribers are not first-class.** The listener model assumes the caller is itself a session with a host pane reachable via the listener-message path. A purely external observer (e.g., a UI adapter wanting "tell me when session T stops") is not represented as a listener record — that fan-out lives in the agent-coordinator emit path, separate from this surface.

## See Also

- docs/local/spec/feature/agent_runtime/control-delivery.md
- docs/local/spec/feature/agent_runtime/session-transcript-retrieval.md
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- ~/.teleclaude/docs/general/policy/human-contract.md
