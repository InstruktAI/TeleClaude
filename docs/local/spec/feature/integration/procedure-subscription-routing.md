---
description: Verified events are matched against the procedure subscriptions published
  for their company, and each match produces one activation naming the procedure and
  that company; publication is what makes a subscription live.
visibility: internal
---

# Procedure Subscription Routing — Spec

## What it is

Procedure subscription routing is the step between a verified event and the
agent that answers it. An event that has reached the cluster is matched against
the procedure subscriptions published for the company its configured source is
associated with. A match produces one activation naming the procedure and that
company, and hands it to the runtime contract that owns standing agents.
Routing decides nothing about whether an agent already stands, and never starts
or addresses a session itself.

The company comes from the event source's own declaration and travels with the
event from the ingress. It is never derived from the procedure's name or from
any checkout location. The event names no consumer: every computer receives it,
and each computer first looks up whether that company is configured on it. A
computer that hosts the company matches the event; any other computer does
nothing, which is the normal case rather than a failure.

A published subscription is live for the company it is published to.
Publication is the registration: nothing stands between an author declaring the
events a procedure answers to and those events reaching it.

## Canonical fields

### Use cases

#### UC-PSR1: A matched event produces one activation naming the procedure and company

```gherkin
Given a procedure published for a company declares an event type as activating it
And a verified event of that type arrives from a source associated with that company
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees exactly one activation naming that procedure and that company
And that activation carries the event's context
And the agent sees no session started or addressed by the match itself
```

#### UC-PSR2: Publication is the registration

```gherkin
Given a procedure declaring the events that activate it is published for a company
And no act beyond that publication has been performed
When a verified event of a declared type arrives from a source associated with that company
Then an agent inspecting the activation record sees an activation for that procedure and company
```

#### UC-PSR3: An unmatched event produces no activation

```gherkin
Given a verified event arrives from a source associated with a company
And no procedure published for that company declares its type
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees no activation for that event
And sees no failure recorded for the absence of a match
```

#### UC-PSR4: Matching is scoped to the source's company

```gherkin
Given two companies each publish a procedure declaring the same event type
When a verified event arrives from a source associated with one of those companies
Then an agent inspecting the activation record sees an activation for that company only
And sees none for the other company
```

#### UC-PSR5: The activation names a system origin, not a fabricated human one

```gherkin
Given a verified event arrives from a source associated with a company
When a match produces an activation for a published procedure
Then an agent inspecting the activation sees the platform's system principal named as its origin
And sees no human principal presented as having initiated it
```

#### UC-PSR7: A computer that does not host the event's company produces no activation

```gherkin
Scenario Outline: Nothing activates where the company is not hosted
  Given a computer publishes a procedure declaring an event type as activating it
  And a verified event of that type reaches the computer <company condition>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting that computer's activation record sees no activation for the event
  And sees no failure recorded for it

  Examples:
    | company condition                                     |
    | naming a company that is not configured on it         |
    | carrying no company                                   |
```

### Cross-context references

- **context** — publishes the procedure subscriptions this context matches
  against; this context never inspects the documentation corpus itself or
  decides what may be published into it.
- **config** — owns the association between a configured event source and its
  company.
- **agent_runtime** — receives the activation and owns everything after it:
  whether an agent already stands, starting or waking it, and the principal and
  company it is bound to.

## Known caveats

- Matching establishes that a procedure's attention is due. It establishes
  nothing about whether a business mutation is necessary; a duplicate, late, or
  superseded event still reaches its group and is reconciled by the activated
  procedure.

## See Also

- docs/local/spec/feature/integration/single-ingress-webhook-termination.md — how a verified external event reaches the cluster before this matching runs.
- docs/local/spec/feature/integration/subscriber-driven-contract-routing.md — the subscriber-published Contract model this context already routes with.
