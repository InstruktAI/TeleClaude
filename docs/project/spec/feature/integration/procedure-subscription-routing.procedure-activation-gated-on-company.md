---
description: Verified events are matched against the procedure subscriptions published
  for their activation scope — a company, a person, or a project — and each match produces
  one activation naming the procedure and that scope; publication is what makes a
  subscription live.
visibility: internal
---

# Procedure Subscription Routing — Spec

## What it is

Procedure subscription routing is the step between a verified event and the
agent that answers it. An event that has reached the cluster carries at most
one activation scope — a company, a person, or a project — and is matched
against the procedure subscriptions published for that scope. A match produces
one activation naming the procedure and the scope, and hands it to the runtime
contract that owns standing agents. Routing decides nothing about whether an
agent already stands, and never starts or addresses a session itself.

The event's scope is its company when it carries one, otherwise its person,
otherwise its project. That scope comes from the event source's own
declaration and travels with the event from the ingress. It is never derived
from the procedure's name or from any checkout location. The event names no
consumer: every computer receives it, and each computer first looks up whether
that scope is configured on it. A computer that hosts the scope matches the
event; any other computer does nothing, which is the normal case rather than a
failure.

A published subscription is live for the reach its publication tier gives it:
a procedure published at global tier answers every scope, one published in a
company's tier answers that company only, and one published in a person's tier
answers that person only. The event's scope decides reach: a procedure
published in a company's or a person's tier is activated only when the event's
scope is that company or person, so an event carrying more than one scope field
never activates a tier procedure for a scope the event does not select.
Publication is the registration: nothing stands
between an author declaring the events a procedure answers to and those events
reaching it.

## Canonical fields

### Use cases

#### UC-PSR1: A matched event produces one activation naming the procedure and scope

```gherkin
Given a procedure published for a scope declares an event type as activating it
And a verified event of that type arrives from a source associated with that scope
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees exactly one activation naming that procedure and that scope
And that activation carries the event's context
And the agent sees no session started or addressed by the match itself
```

#### UC-PSR2: Publication is the registration

```gherkin
Given a procedure declaring the events that activate it is published for a scope
And no act beyond that publication has been performed
When a verified event of a declared type arrives from a source associated with that scope
Then an agent inspecting the activation record sees an activation for that procedure and scope
```

#### UC-PSR3: An unmatched event produces no activation

```gherkin
Given a verified event arrives from a source associated with a scope
And no procedure published for that scope declares its type
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
Given a verified event arrives from a source associated with a scope
When a match produces an activation for a published procedure
Then an agent inspecting the activation sees the platform's system principal named as its origin
And sees no human principal presented as having initiated it
```

#### UC-PSR7: A computer that does not host the event's scope produces no activation

```gherkin
Scenario Outline: Nothing activates where the scope is not hosted
  Given a computer publishes a procedure declaring an event type as activating it
  And a verified event of that type reaches the computer <scope condition>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting that computer's activation record sees no activation for the event
  And sees no failure recorded for it

  Examples:
    | scope condition                                       |
    | naming a company that is not configured on it         |
    | naming a person who is not registered on it           |
    | naming a project that is not registered on it         |
    | carrying no company, person, or project               |
```

#### UC-PSR8: An event without a company activates for its person or its project

```gherkin
Scenario Outline: The event's scope decides which agent is activated
  Given a procedure published at global tier declares an event type as activating it
  And a verified event of that type arrives carrying <carried scope> that is configured on the computer
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting the activation record sees exactly one activation naming that procedure and <activated scope>

  Examples:
    | carried scope        | activated scope |
    | a company            | that company    |
    | a person             | that person     |
    | a project            | that project    |
```

#### UC-PSR9: A person-tier subscription answers only that person

```gherkin
Given a procedure published in a person's tier declares an event type as activating it
When verified events of that type arrive, one carrying that person and one carrying another scope
Then an agent inspecting the activation record sees an activation for that person
And sees none for the event carrying the other scope
```

#### UC-PSR10: A tier procedure answers only the event's selected scope

```gherkin
Given a procedure published in a person's tier declares an event type as activating it
And a verified event of that type carries both a company and that person
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees no activation for that person's procedure
And sees a routing decision naming the event's selected scope as one the procedure is not published for
And sees no failure recorded for it
```

### Cross-context references

- **context** — publishes the procedure subscriptions this context matches
  against, with the tier each is published at; this context never inspects the
  documentation corpus itself or decides what may be published into it.
- **config** — owns the association between a configured event source and its
  company, person, or project, and whether each is configured on a computer.
- **agent_runtime** — receives the activation and owns everything after it:
  whether an agent already stands, starting or waking it, the home it works in,
  and the principal and company it is bound to.

## Known caveats

- Matching establishes that a procedure's attention is due. It establishes
  nothing about whether a business mutation is necessary; a duplicate, late, or
  superseded event still reaches its group and is reconciled by the activated
  procedure.
- A procedure published in a project's own tier is not part of the publication
  index this context matches against, so project-scoped activation is answered
  by procedures published at global tier.

## See Also

- docs/project/spec/feature/integration/single-ingress-webhook-termination.md — how a verified external event reaches the cluster before this matching runs.
- docs/project/spec/feature/integration/subscriber-driven-contract-routing.md — the subscriber-published Contract model this context already routes with.
- docs/project/spec/feature/integration/inbound-webhook-endpoint-framework.md — how the ingress stamps the source's declared scope onto every event.
