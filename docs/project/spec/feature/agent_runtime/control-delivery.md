---
description: Durable per-session control-payload delivery into running agent turns
  at natural work boundaries, with claim receipts, staleness expiry, and an idle-wake
  fallback.
delivered_by:
  - control-outbox-hook-delivery
---

# Control Delivery — Spec

## What it is

The control-delivery surface carries platform-authored control payloads —
reminder firings and other non-conversational control traffic — into an agent
session without typing into its terminal. A payload for a session with a
running turn is delivered inside that turn at the next natural boundary of the
agent's work; a payload for an idle session wakes it through the existing
session-input surface. Handing a payload to this surface is delivery from the
producer's perspective: the producer neither tracks nor retries beyond the
handoff.

Delivery is claim-based. The first delivery opportunity that observes a pending
payload claims it; a claimed payload is consumed and never delivered twice. The
surface owns receipts, redelivery after a failed claim, staleness expiry, and
ordering. Human-facing surfaces render none of this traffic; conversational
messages between agents and humans do not ride this surface.

## Canonical fields

A pending control payload carries:

- owning session identity;
- payload body — the same platform-authored envelope text the receiving agent
  vocabulary already recognizes;
- enqueue instant, claim instant, delivery instant;
- attempt count and expiry instant.

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
Then the pending payload is delivered at the turn's completion boundary
And the agent processes it before the session goes idle
```

#### UC-CDL3: An idle session is woken through the existing input surface

```gherkin
Given a control payload is pending for a session with no running turn
When the platform detects that no in-turn delivery opportunity is coming
Then the payload is delivered by waking the session through the existing session-input surface
And in-turn delivery is preferred whenever a turn is running
```

#### UC-CDL4: A claimed payload is delivered exactly once

```gherkin
Given a pending control payload
When a delivery opportunity claims it
Then the payload is consumed and no later opportunity delivers it again
And a claim that fails before delivery completes is released after a bounded interval
And the released payload becomes pending again with its attempt recorded
```

#### UC-CDL5: Stale payloads expire instead of arriving late

```gherkin
Given a control payload remains undelivered past its expiry instant
When the platform next evaluates it
Then the payload is expired and never delivered
And the expiry is visible in structured operational evidence
```

#### UC-CDL6: One session's payloads arrive in order

```gherkin
Given several control payloads are pending for one session
When delivery opportunities consume them
Then the payloads arrive in their enqueue order
```

#### UC-CDL7: Control traffic is invisible to human surfaces

```gherkin
Given control payloads are enqueued, delivered, or expired for a session
When a human reads that session's conversational surfaces
Then no control-delivery traffic is rendered there
And the session transcript remains the inspectable record of what the agent received
```

## Known caveats

- Delivery means the payload was handed into the agent's context; no runtime
  confirms that the model acted on it. The receiving agent's contracts govern
  what happens next.
- A single long-running tool action is not interrupted; the payload waits for
  the boundary that follows it. Preempting in-flight work is a deliberate
  session interrupt, not a control delivery.
- Wake delivery into an occupied composer is governed by the session-input
  surface's occupancy contract, not by this surface.
