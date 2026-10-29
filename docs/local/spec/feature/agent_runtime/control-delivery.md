---
description: Durable per-session control-payload delivery into running agent turns
  at natural work boundaries, with ordered handoff, session-close cleanup, and an
  idle-wake trigger.
---

# Control Delivery — Spec

## What it is

<!-- planned-change:antigravity-native-subagents-allowed -->

The control-delivery surface carries platform-authored control payloads —
reminder firings and other non-conversational control traffic — into an agent
session. A payload reaches the agent at the first moment the session offers:
the next natural boundary of the agent's work while one is certain to follow,
otherwise a wake that produces one. A pending payload for a session that can be
woken never waits on input that is not certain to arrive.

<!-- change:antigravity-native-subagents-allowed -->

The control-delivery surface carries platform-authored control payloads —
reminder firings, checkpoints relayed from a hook that cannot continue the
conversation owning the turn
(`local/projects/teleclaude/design/architecture/checkpoint-system`), and other
non-conversational control traffic — into an agent session. A payload reaches the agent at the first moment the session offers:
the next natural boundary of the agent's work while one is certain to follow,
otherwise a wake that produces one. A pending payload for a session that can be
woken never waits on input that is not certain to arrive.

<!-- /planned-change:antigravity-native-subagents-allowed -->

Inside a running turn the payload is delivered at its next supported mid-turn boundary,
with no terminal write. When the platform holds a pending payload and knows no
boundary is coming — the producer observes no running turn, or the platform
records the end of a turn while a payload is still pending — the session is
woken so that a boundary exists, and delivery then happens through that
boundary like any other; only that minimal wake trigger reaches the terminal,
never the control payload itself. Handing a payload to this surface is delivery
from the producer's perspective: the producer neither tracks nor retries beyond
the handoff.

Delivery and wake each depend on what the session can receive. Every session
whose agent runtime declares delivery boundaries receives payloads at those
boundaries. Only a session bound to a host pane can be woken, because the wake
is typed input. A session reached through its hooks alone — the headless
session of an agent running outside the platform — is never typed into, since
typed input adopts a headless session
(`local/projects/teleclaude/spec/feature/agent_runtime/session-input-delivery`);
its pending payload is delivered at its next hook boundary, which arrives with
that agent's next turn.

Stop-hook responses carry checkpoint obligations only
(`sdlc/principle/design-fundamentals`); control payloads remain pending through
that boundary. A checkpoint continuation offers its subsequent
mid-turn boundaries for eligible payloads. An accepted stop records the turn end
and wakes pending work through the existing session-input surface. Runtime adapters declare their
supported injection boundaries, including invocation boundaries where a native
post-tool hook cannot carry context.

Delivery boundaries for one session are ordered by the agent runtime, and this
surface relies on that contract rather than arbitrating between simultaneous
opportunities. The first boundary to observe a pending payload takes it and
records the outcome, so a later boundary never re-delivers it. A payload
reaches exactly one of two terminal outcomes: delivered, or failed. A failed
handoff is never retried and never returns to pending. Human-facing surfaces
render none of this traffic; conversational messages between agents and humans
do not ride this surface.

Procedure activation events use this hook transport with the eligibility and
cardinality contract owned by
`local/projects/teleclaude/spec/feature/agent_runtime/procedure-event-delivery`.
The natural-boundary, whole-batch, and session-owned cleanup behavior described
here is the default for existing control producers. Procedure events retain
their declared boundary and selection rules; an ineligible row stays pending
when other control traffic is drained. Closing a session releases its transport
records only after pending procedure work is accounted for by the continuing
responsibility or an explicit terminal failure. Event data retains its untrusted
provenance inside the transport (`general/policy/message-identity-headers`).

Closing a session discards its remaining control payloads after procedure-event
work is accounted for. A control payload already in flight is abandoned and
logged without blocking closure. A producer may supersede only its own pending
payload when it declares the same envelope kind and key; the old payload is
removed without delivery and the replacement keeps its enqueue position.

## Canonical fields

A control payload record carries:

- owning session identity;
- the semantic envelope kind, label, closure discipline, structured header
  fields, and body owned by the shared message-envelope registry;
- enqueue instant.

The record stores semantics rather than rendered framing. At the hook boundary,
control delivery renders the record through the XML codec over that shared
model. The content-free idle wake takes the bracket codec because it is typed
into a human-readable composer. No producer supplies already-rendered bracket
or XML framing to this surface.

While the payload is pending it carries no terminal outcome and no outcome
instant. Reaching a terminal outcome sets both together: the outcome, delivered
or failed, and the instant it was reached. Each delivery boundary selects the
entire pending batch in enqueue order and records one terminal outcome for the
whole batch; partial delivery is not represented.

### Use cases

#### UC-CDL1: A payload reaches a working agent inside its running turn

#### UC-CDL2:

#### UC-CDL3: An idle session is woken so a delivery boundary exists

#### UC-CDL4: A payload is consumed on successful handoff, and a failed handoff fails loudly

#### UC-CDL5: Closing a session discards its undelivered payloads

#### UC-CDL6: One boundary drains everything pending, in order, as one batch

#### UC-CDL7: A person can converse without control traffic in their view

```gherkin
Given a person is conversing with an agent while platform control payloads are pending
When they read their conversation surfaces
Then no control-delivery traffic is rendered there
And the session transcript remains the inspectable record of what the agent received
```

#### UC-CDL8: Hook delivery and idle wake render one model through distinct codecs

#### UC-CDL9: A turn that ends in a provider failure leaves the session idle for the next control payload

#### UC-CDL10: A producer supersedes its own undelivered payload

#### UC-CDL11: A payload that lands while a turn is ending is woken in at the turn's end

#### UC-CDL12:

#### UC-CDL13:

<!-- planned:failed-control-wake-leaves-session-running -->

#### UC-CDL14: A wake that ends undelivered leaves the session idle for the next control payload

```gherkin
Given an idle session whose wake for a pending control payload was accepted
And that wake ends undelivered without the agent starting a turn
And no other input has started a turn since
When a later control payload is handed off while the session can be woken
Then the session is woken for that payload
```

<!-- /planned:failed-control-wake-leaves-session-running -->

## Known caveats

- This surface's contract ends at its own boundary: a semantic payload rendered
  by the XML codec on an event documented to accept injected content. That is
  what delivery asserts and all it asserts.
- The batch is recorded only after a successful handoff, so a process death
  between the two rolls the record back and the next boundary re-delivers. That
  window needs a process death, not a race.
- The injection channel is one-directional. Nothing downstream acknowledges
  receipt, and no runtime confirms that the model acted on a payload. Delivery
  is never conditioned on a downstream signal.
- A well-formed payload emitted on a documented injectable event and then
  silently discarded is a violation of that runtime's contract. It is reported
  as a defect against the runtime, never accommodated by logic on this side.
- A single long-running tool action is not interrupted; the payload waits for
  the boundary that follows it. Preempting in-flight work is a deliberate
  session interrupt, not a control delivery.
- Waking into an occupied composer is governed by the session-input surface's
  occupancy contract, not by this surface.
- The platform's view of whether a turn is running trails the runtime: a turn
  end reaches the platform only after the runtime's last boundary has already
  run. A payload handed off in that interval sees a running turn and is not
  woken by its producer; the wake at the recorded turn end delivers it. Each
  side reads the other's write after making its own, so one of them always
  wakes the session. Both may wake it for the same payload; the wake carries
  that payload's occurrence identity, so the session-input surface accepts it
  once.
- Ordered delivery boundaries are a contract of the agent runtimes, relied on
  rather than enforced here. This surface's once-only property holds only while
  that contract holds.
