---
description: One standing agent per procedure per company — identified by the procedure's own canonical ID and the company, started by the first activation and woken by every later one.
visibility: internal
delivered_by:
  - procedure-event-activation
---

# Procedure Standing Agent — Spec

## What it is

A procedure that declares the events activating it owns one continuing agent per
company. That agent is identified by two facts: the procedure's existing
canonical ID and the company whose business it operates. The first activation starts it; every later activation is
delivered to the agent already standing, whether it is idle or in the middle of
a turn.

The procedure's ID is the identity. Its declared subscriptions are its event
membership and nothing more — there is no separate group identifier and no
group entity to register or manage. Two consequences follow: procedures whose
event lists overlap remain distinct responsibilities with distinct agents, and
editing a procedure's event list changes what its agent listens to without
changing which agent it is.

A standing agent is started by an event, so it runs under the platform's system
principal with the company mapped from the event's source. The principal is
therefore the same for every standing agent and is not part of its identity.

A standing agent is a session, so it lives on one computer, and each computer
decides for itself. On a computer that hosts the company, the activation runner
wakes an agent already running the procedure for that company when it finds one
or more, and starts one only when it finds none. That is the runner's own
behavior: nothing restricts starting such an agent by hand, and nothing
coordinates computers.

A standing agent is an ordinary scoped session. Standing confers no platform
role authority: it is not the integrator, the project coordinator, or a job
runner, and acquires none of their powers by continuing.

## Canonical fields

### Ubiquitous language

**Standing agent**
: The single live session that continues a procedure's work for one company.

**Activation**
: One delivery of a matched event to a procedure's standing agent — a start when none stands, a wake when one does.

### Use cases

#### UC-PSA1: The first activation starts the procedure's standing agent

```gherkin
Given no standing agent continues a procedure for a company
When an activation for that procedure and company arrives
Then a standing agent is started
And the agent receives the procedure
And the agent receives the arriving activation's event context
```

#### UC-PSA2: A later activation reaches the agent already standing

```gherkin
Given a standing agent continues a procedure for a company
When a further activation for that procedure and company arrives
Then the activation is delivered to that same agent
And no second agent is started
And delivery occurs whether that agent is idle or in the middle of a turn
```

#### UC-PSA3: Every declared event reaches the one standing agent

```gherkin
Given a procedure declares several event types as activating it
And a standing agent continues that procedure for a company
When an activation arrives for any one of those event types
Then it reaches that one standing agent
```

#### UC-PSA4: Editing the event list does not change the continuing agent

```gherkin
Given a standing agent continues a procedure for a company
When an event type is added to or removed from that procedure's declared subscriptions
Then the same agent continues the procedure
And no additional standing agent is started for it
And the agent listens to the amended set of event types
```

#### UC-PSA5: Overlapping subscriptions do not merge responsibilities

```gherkin
Given two distinct procedures each declare the same event type as activating them
And both are published for one company
When an activation for that event type arrives
Then each procedure's standing agent is activated
And neither procedure's responsibility is absorbed into the other
```

#### UC-PSA6: Procedure and company each identify a distinct agent

```gherkin
Scenario Outline: A difference on either identity dimension yields a separate agent
  Given two continuing responsibilities that differ in <dimension> and agree on the other
  When an activation arrives for each of them
  Then each is continued by its own standing agent
  And an activation for one never reaches the other

  Examples:
    | dimension |
    | procedure |
    | company   |
```

#### UC-PSA7: Concurrent activations produce one standing agent

```gherkin
Given no standing agent continues a procedure for a company
When two activations for that procedure and company arrive concurrently
Then exactly one standing agent continues it afterwards
And both activations reach that agent
```

#### UC-PSA8: The company and system origin survive every continuation

```gherkin
Scenario Outline: Continuing the work preserves the company and origin it was bound to
  Given a standing agent operating a company under the system principal
  When the agent <continuation>
  Then the same company and system origin still govern the work
  And the activation's own data does not replace them
  And the agent does not act as any person the activation refers to

  Examples:
    | continuation                   |
    | is woken by a later activation |
    | is restarted                   |
    | dispatches a worker            |
```

#### UC-PSA9: An activation that cannot be fulfilled is observable as a failure

```gherkin
Given an activation for a procedure and company arrives
And it cannot be fulfilled
When the platform records the outcome
Then an agent inspecting the activation record observes a failure
And the record does not present the activation as completed
And the procedure's responsibility is not transferred to another agent
```

#### UC-PSA10: An agent already running the procedure for the company counts as standing

```gherkin
Given an agent was started by hand to run a procedure for a company on a computer
When an activation for that procedure and company arrives on that computer
Then the activation is delivered to an agent already running it
And no further agent is started
```

#### UC-PSA11: Starting an agent by hand is never refused

```gherkin
Given a standing agent runs a procedure for a company on a computer
When an operator or agent starts another session for that procedure and company by hand
Then that session starts
And the activation runner raises no objection to it
```

### Cross-context references

- **integration** — hands this context an activation naming the procedure and
  the company; it never starts or addresses a session itself.
- **identity** — owns the system-principal contract a standing agent runs
  under. This context decides nothing about identity and derives no
  authorization the identity contract does not publish.
- **context** — publishes the procedure and the event types it declares.

## Known caveats

- Standing is not remembering. A long-lived agent compacts; what it recovers
  afterward rests on durable state its procedure and domain own.
- The standing population is bounded by the published procedures and the
  companies they serve. Workers a standing agent dispatches are a separate,
  bounded source of concurrency.

## See Also

- docs/project/spec/feature/agent_runtime/company-scoped-session-context.md — how a session's company and origin are established, carried, and published.
- docs/project/spec/feature/agent_runtime/coordinator-role-acquisition.md — the other singleton in this context: human-directed, one per project instance, enforced at an acquisition door rather than by activation.
- docs/project/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md — the schedule-driven sibling, which creates a session per run rather than keeping one standing.
