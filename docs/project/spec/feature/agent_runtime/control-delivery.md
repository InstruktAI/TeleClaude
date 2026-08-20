---
description: Durable per-session control-payload delivery into running agent turns
  at natural work boundaries, with ordered handoff, session-close cleanup, and an
  idle-wake trigger.
delivered_by:
  - control-outbox-hook-delivery
---

# Control Delivery — Spec

## What it is

The control-delivery surface carries platform-authored control payloads —
reminder firings and other non-conversational control traffic — into an agent
session without typing into its terminal. A payload for a session with a
running turn is delivered inside that turn at the next natural boundary of the
agent's work; a session with no running turn is woken so that a boundary exists,
and delivery then happens through that boundary like any other. Handing a payload
to this surface is delivery from the producer's perspective: the producer neither
tracks nor retries beyond the handoff.

Delivery boundaries for one session are ordered by the agent runtime, and this
surface relies on that contract rather than arbitrating between simultaneous
opportunities. The first boundary to observe a pending payload takes it and
records the outcome, so a later boundary never re-delivers it. A handoff that
fails is a defect in this machinery rather than a transient condition: it fails
loudly instead of being retried, because the next boundary would fail the same
way. Human-facing surfaces render none of this traffic; conversational messages
between agents and humans do not ride this surface.

## Canonical fields

A pending control payload carries:

- owning session identity;
- payload body — the same platform-authored envelope text the receiving agent
  vocabulary already recognizes;
- enqueue instant and delivery instant.

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
Then the session is woken through the existing session-input surface
And the payload is delivered at the boundary that waking produces, not carried by the wake itself
And in-turn delivery is preferred whenever a turn is running
```

#### UC-CDL4: A payload is consumed on successful handoff, and a failed handoff fails loudly

```gherkin
Given a pending control payload
When a delivery boundary hands the payload off successfully
Then the payload is consumed at that moment without waiting for downstream confirmation
And no later boundary delivers it again
But when the handoff itself fails
Then the failure is raised rather than retried at a later boundary
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
And the whole batch is consumed together once that handoff succeeds
But when the handoff fails
Then no payload in the batch is consumed
```

#### UC-CDL7: Control traffic is invisible to human surfaces

```gherkin
Given control payloads are enqueued, delivered, or discarded at session close
When a human reads that session's conversational surfaces
Then no control-delivery traffic is rendered there
And the session transcript remains the inspectable record of what the agent received
```

## Known caveats

- This surface's contract ends at its own boundary: a correctly shaped payload,
  emitted successfully on an event documented to accept injected content. That
  is what "delivered" asserts and all it asserts.
- The injection channel is one-directional. Nothing downstream acknowledges
  receipt, and no runtime confirms that the model acted on a payload. Delivery
  is therefore never conditioned on a downstream signal, because none exists.
- A well-formed payload emitted on a documented injectable event and then
  silently discarded is a violation of that runtime's contract. It is reported
  as a defect against the runtime, never accommodated by logic on this side.
- A single long-running tool action is not interrupted; the payload waits for
  the boundary that follows it. Preempting in-flight work is a deliberate
  session interrupt, not a control delivery.
- Waking into an occupied composer is governed by the session-input surface's
  occupancy contract, not by this surface.
- Ordered delivery boundaries are a contract of the agent runtimes, relied on
  rather than enforced here. A runtime that delivered boundaries out of order or
  simultaneously would break this surface's once-only property.
