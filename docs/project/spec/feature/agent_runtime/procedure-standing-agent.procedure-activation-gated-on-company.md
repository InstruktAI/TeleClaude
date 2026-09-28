---
description: One standing agent per procedure per activation scope — a company, a person,
  or a project — identified by the procedure's own canonical ID and that scope, started in
  the scope's home by the first activation and woken by every later one.
visibility: internal
---

# Procedure Standing Agent — Spec

## What it is

A procedure that declares the events activating it owns one continuing agent per
activation scope. A scope is a company, a person, or a project, named by its
kind and its slug. The agent is identified by two facts: the procedure's
existing canonical ID and the scope whose work it carries. The first activation
starts it; every later activation is delivered to the agent already standing,
whether it is idle or in the middle of a turn.

The procedure's ID is the identity. Its declared subscriptions are its event
membership and nothing more — there is no separate group identifier and no
group entity to register or manage. Two consequences follow: procedures whose
event lists overlap remain distinct responsibilities with distinct agents, and
editing a procedure's event list changes what its agent listens to without
changing which agent it is.

A standing agent works in its scope's home: a company's home, a person's
folder, or a project's checkout on that computer. An agent for a company scope
has the session's company set to that company; an agent for a person or a
project has no company, because location never supplies one
(`project/spec/feature/agent_runtime/company-scoped-session-context`).

A standing agent is started by an event, so it runs under the platform's system
principal with the scope mapped from the event's source. The principal is
therefore the same for every standing agent and is not part of its identity.

A standing agent is a session, so it lives on one computer, and each computer
decides for itself. On a computer that hosts the scope, the activation runner
wakes a session already running the procedure for that scope under the system
principal when it finds one or more, and starts one only when it finds none.
That is the runner's own behavior: nothing restricts starting such an agent by
hand, and nothing coordinates computers.

A standing agent is an ordinary scoped session. Standing confers no platform
role authority: it is not the integrator, the project coordinator, or a job
runner, and acquires none of their powers by continuing. An agent working in a
person's folder carries no human identity and acts as no person.

## Canonical fields

### Ubiquitous language

**Activation scope**
: The one company, person, or project an activation concerns, named by its kind and slug.

**Scope home**
: Where a standing agent works — the company's home, the person's folder, or the project's checkout on the computer.

**Standing agent**
: The single live session that continues a procedure's work for one activation scope.

**Activation**
: One delivery of a matched event to a procedure's standing agent — a start when none stands, a wake when one does.

### Use cases

#### UC-PSA1: The first activation starts the procedure's standing agent

```gherkin
Given no standing agent continues a procedure for a scope on a computer that hosts the scope
When an activation for that procedure and scope arrives there
Then a standing agent is started in that scope's home under the system principal
And its complete instruction set is the procedure together with its required reads
And it receives the triggering event as its first input, through the same delivery path later activations take
And the event is not supplied as startup context
```

#### UC-PSA2: A later activation reaches the agent already standing

```gherkin
Given a standing agent continues a procedure for a scope
When a further activation for that procedure and scope arrives
Then the activation is delivered to that same agent
And no second agent is started
And delivery occurs whether that agent is idle or in the middle of a turn
```

#### UC-PSA3: Every declared event reaches the one standing agent

```gherkin
Given a procedure declares several event types as activating it
And a standing agent continues that procedure for a scope
When an activation arrives for any one of those event types
Then it reaches that one standing agent
```

#### UC-PSA4: Editing the event list does not change the continuing agent

```gherkin
Given a standing agent continues a procedure for a scope
When an event type is added to or removed from that procedure's declared subscriptions
Then the same agent continues the procedure
And no additional standing agent is started for it
And the agent listens to the amended set of event types
```

#### UC-PSA5: Overlapping subscriptions do not merge responsibilities

```gherkin
Given two distinct procedures each declare the same event type as activating them
And both are published for one scope
When an activation for that event type arrives
Then each procedure's standing agent is activated
And neither procedure's responsibility is absorbed into the other
```

#### UC-PSA6: Procedure and scope each identify a distinct agent

```gherkin
Scenario Outline: A difference on either identity dimension yields a separate agent
  Given two continuing responsibilities that differ in <dimension> and agree on the rest
  When an activation arrives for each of them
  Then each is continued by its own standing agent
  And an activation for one never reaches the other

  Examples:
    | dimension                                 |
    | procedure                                 |
    | company                                   |
    | scope kind, for scopes sharing one slug   |
```

#### UC-PSA7: Concurrent activations produce one standing agent

```gherkin
Given no standing agent continues a procedure for a scope
When two activations for that procedure and scope arrive concurrently
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
Given an activation for a procedure and scope arrives
And it cannot be fulfilled
When the platform records the outcome
Then an agent inspecting the activation record observes a failure
And the record does not present the activation as completed
And the procedure's responsibility is not transferred to another agent
```

#### UC-PSA10: A system-origin session already running the procedure for the company counts as standing

```gherkin
Given a session under the system principal was started by hand to run a procedure for a company on a computer
When an activation for that procedure and company arrives on that computer
Then the activation is delivered to that session
And no further agent is started
```

#### UC-PSA11: Starting an agent by hand is never refused

```gherkin
Given a standing agent runs a procedure for a company on a computer
When an operator or agent starts another session for that procedure and company by hand
Then that session starts
And the activation runner raises no objection to it
```

#### UC-PSA12: A human-lineage session running the procedure is not adopted

```gherkin
Given a session carrying human lineage runs a procedure for a scope on a computer
And no session under the system principal runs that procedure for that scope there
When an activation for that procedure and scope arrives on that computer
Then a standing agent is started under the system principal
And the activation is not delivered to the human-lineage session
```

#### UC-PSA13: A person or project activation starts its agent in that home without a company

```gherkin
Scenario Outline: The scope's home is where the agent works
  Given no standing agent continues a procedure for <scope> on a computer that hosts it
  When an activation for that procedure and <scope> arrives there
  Then a standing agent is started in <home> under the system principal
  And an agent inspecting the session sees no company set on it

  Examples:
    | scope     | home                              |
    | a person  | that person's folder              |
    | a project | that project's checkout           |
```

### Cross-context references

- **integration** — hands this context an activation naming the procedure and
  the scope; it never starts or addresses a session itself.
- **config** — answers whether a company, person, or project is configured on
  the computer, and where its home is.
- **identity** — owns the system-principal contract a standing agent runs
  under. This context decides nothing about identity and derives no
  authorization the identity contract does not publish.
- **context** — publishes the procedure and the event types it declares.

## Known caveats

- Standing is not remembering. A long-lived agent compacts; what it recovers
  afterward rests on durable state its procedure and domain own.
- The standing population is bounded by the published procedures and the
  scopes they serve. Workers a standing agent dispatches are a separate,
  bounded source of concurrency.
- Starting a standing agent by hand is available for a company scope only; a
  person- or project-scoped agent is started by an activation.

## See Also

- docs/project/spec/feature/agent_runtime/company-scoped-session-context.md — how a session's company and origin are established, carried, and published.
- docs/project/spec/feature/agent_runtime/coordinator-role-acquisition.md — the other singleton in this context: human-directed, one per project instance, enforced at an acquisition door rather than by activation.
- docs/project/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md — the schedule-driven sibling, which creates a session per run rather than keeping one standing.
