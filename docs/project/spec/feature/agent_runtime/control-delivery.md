---
description: Durable per-session control-payload delivery into running agent turns
  at natural work boundaries, with ordered handoff, session-close cleanup, and an
  idle-wake trigger.
---

# Control Delivery — Spec

## What it is

The control-delivery surface carries platform-authored control payloads —
reminder firings and other non-conversational control traffic — into an agent
session. A payload for a session with a running turn is delivered inside that
turn at the next natural boundary of the agent's work, with no terminal write.
A session with no running turn is woken so that a boundary exists, and delivery
then happens through that boundary like any other; only that minimal wake
trigger reaches the terminal, never the control payload itself. Handing a
payload to this surface is delivery from the producer's perspective: the
producer neither tracks nor retries beyond the handoff.

Delivery boundaries for one session are ordered by the agent runtime, and this
surface relies on that contract rather than arbitrating between simultaneous
opportunities. The first boundary to observe a pending payload takes it and
records the outcome, so a later boundary never re-delivers it. A payload
reaches exactly one of two terminal outcomes: delivered, or failed. A failed
handoff is never retried and never returns to pending. Human-facing surfaces
render none of this traffic; conversational messages between agents and humans
do not ride this surface.

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
or failed, and the instant it was reached.

### Use cases

#### UC-CDL1: A payload reaches a working agent inside its running turn

```gherkin
Given a control payload is pending for a session whose agent is mid-turn doing tool-assisted work
When the agent's work reaches its next natural boundary
Then the payload is delivered into the running turn at that boundary
And the turn is not ended or restarted by the delivery
And nothing is typed into the session's terminal
```

#### UC-CDL2: A turn without natural boundaries receives payloads at its end

```gherkin
Given a control payload is pending for a session whose current turn performs no tool-assisted work
When that turn completes
Then the pending payload is handed into that turn at its completion boundary
And the handoff completes before the session goes idle
```

#### UC-CDL3: An idle session is woken so a delivery boundary exists

```gherkin
Given a control payload is pending for a session with no running turn
When the platform detects that no delivery boundary is coming
Then the session is woken by a minimal trigger typed through the existing session-input surface
And that trigger is the only content reaching the terminal, never the control payload
And the payload is delivered at the boundary that waking produces
And in-turn delivery is preferred whenever a turn is running
```

#### UC-CDL4: A payload is consumed on successful handoff, and a failed handoff fails loudly

```gherkin
Given a pending control payload
When a delivery boundary hands the payload off successfully
Then the payload is recorded delivered at that moment without waiting for downstream confirmation
And no later boundary delivers it again
But when the handoff itself fails
Then the payload is recorded failed, which is terminal
And the failure is raised
And no later boundary retries it or finds it pending again
```

#### UC-CDL5: Closing a session discards its undelivered payloads

```gherkin
Given undelivered control payloads are pending for a session
When that session closes
Then every payload owned by that session is removed
And a payload whose delivery was in flight at that moment is abandoned with a logged warning
And the close completes without being blocked by the abandoned delivery
```

#### UC-CDL6: One boundary drains everything pending, in order, as one batch

```gherkin
Given several control payloads are pending for one session
When a delivery boundary is reached
Then every payload pending at that moment is handed off together in one delivery
And the payloads appear in their enqueue order within it
And the whole batch is recorded delivered together once that handoff succeeds
But when the handoff fails
Then every payload in the batch is recorded failed together
And no batch ever ends partly delivered or partly pending
```

#### UC-CDL7: Control traffic is invisible to human surfaces

```gherkin
Given control payloads are enqueued, delivered, or discarded at session close
When a human reads that session's conversational surfaces
Then no control-delivery traffic is rendered there
And the session transcript remains the inspectable record of what the agent received
```

#### UC-CDL8: Hook delivery and idle wake render one model through distinct codecs

```gherkin
Given a semantic control envelope is pending for a session
When a running turn reaches a hook delivery boundary
Then the payload is rendered by the XML codec over the shared envelope registry
And no bracket framing is embedded inside that XML payload
But when the session is idle and must be woken
Then the same registered wake model is rendered by the bracket codec as its auto-closed marker
And neither codec declares vocabulary or closure independently of the registry
```

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
- Ordered delivery boundaries are a contract of the agent runtimes, relied on
  rather than enforced here. This surface's once-only property holds only while
  that contract holds.
