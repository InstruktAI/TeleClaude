---
description: One standing agent per procedure per home — identified by the procedure's own canonical ID and the company, person, project, or platform it answers, started in that home on the computer that emitted the activating event by the first activation and woken by every later one.
visibility: internal
---

# Procedure Standing Agent — Spec

## What it is

A procedure that declares the events activating it owns one continuing agent per
activation home, or, when it declares subject identity, one per subject of its
events within that home. A home is a company, a person, or a project, named by
its kind and its slug, or the platform itself for events that concern no
registered home. By default the agent is identified by two facts: the
procedure's existing canonical ID and the home whose work it carries. A
procedure that declares subject identity adds a third: the subject its
activating event is about, so each thing its events concern — a session, a
todo, a job — has an agent of its own and no agent collects every subject in a
home. The first activation for an identity starts its agent; every later
activation for the same identity is delivered to that agent, whether it is idle
or in the middle of a turn. A subject-bound agent whose session has closed is
revived with its own context before the activation is delivered to it.

The procedure's ID is the procedure's part of that identity. Its declared
subscription patterns are its event membership and nothing more — there is no separate group identifier and no
group entity to register or manage. Two consequences follow: procedures whose
patterns overlap remain distinct responsibilities with distinct agents, and
editing a procedure's patterns changes what its agent listens to without
changing which agent it is.

A standing agent works in its home on the computer that emitted the activating
event: a company's home folder, a person's folder, a project's checkout, or, for
the platform, the platform's own checkout. A named home that does not exist on
that computer fails the activation; the work is never moved to another home or
computer. An agent for a company home has the session's company set to that
company; an agent for a person, a project, or the platform has no company,
because location never supplies one
(`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`).

A standing agent is started by an event, so it runs under the platform's system
principal with the origin the event's producer stated. The principal is
therefore the same for every standing agent and is not part of its identity.

A standing agent is a session, so it lives on one computer. Activations arrive
only on the computer that emitted the event, and there the activation runner
wakes a session already running the procedure for that home under the system
principal when it finds one or more, and starts one only when it finds none.
That is the runner's own behavior: nothing restricts starting such an agent by
hand, and nothing coordinates computers.

For a procedure that declares subject identity, the runner finds the session it
started for the procedure, the home and the event's subject on that computer,
open or closed. It delivers to that session when it is open, revives it when it
has closed and can resume its own transcript, and starts a new one bound to the
subject when it finds neither. An activation for such a procedure whose event
names no subject fails, because no agent can be bound to a subject the event
does not state.

An activation carries the identity of the event that produced it. An activation
that repeats one already delivered for the same event, procedure, and home
reaches the agent no second time, within the records the platform retains.

A standing agent is an ordinary scoped session. Standing confers no platform
role authority: it is not the integrator, the project coordinator, or a job
runner, and acquires none of their powers by continuing. An agent working in a
person's folder carries no human identity and acts as no person.

## Canonical fields

### Ubiquitous language

**Activation home**
: The one company, person, or project an activation concerns, as the event's origin names it by kind and slug, or the platform for an event whose origin is none.

**Home folder**
: Where a standing agent works on the emitting computer — the company's home folder, the person's folder, the project's checkout, or the platform's own checkout.

**Standing agent**
: The single live session that continues a procedure's work for one activation home.

**Activation**
: One delivery of a matched event to a procedure's standing agent — a start when none stands, a wake when one does.

**Subject identity**
: A procedure's declaration that each subject of its events within a home has its own agent, instead of one agent for the home.

**Subject-bound agent**
: The agent a procedure declaring subject identity keeps for one subject in one home — started by the first activation about that subject and reached by every later one, revived when its session has closed.

<!-- planned:procedure-agent-headless -->

**Unattended agent**
: The agent of a procedure declaring that no person watches it. It answers, works, and is recorded as any other agent of its procedure; it is left out of the places people look at sessions unless they ask for it.

<!-- /planned:procedure-agent-headless -->

### Use cases

#### UC-PSA1: The first activation starts the procedure's standing agent

```gherkin
Given no standing agent continues a procedure for a home on the computer that emitted the event
When an activation for that procedure and home arrives there
Then a standing agent is started in that home under the system principal
And its complete instruction set is the procedure together with its required reads
And it receives the triggering event as its first input, through the same delivery path later activations take
And the event is not supplied as startup context
```

#### UC-PSA2: A later activation reaches the agent already standing

```gherkin
Given a standing agent continues a procedure for a home
When a further activation for that procedure and home arrives
Then the activation is delivered to that same agent
And no second agent is started
And delivery occurs whether that agent is idle or in the middle of a turn
```

#### UC-PSA3: Every declared event reaches the one standing agent

```gherkin
Given a procedure declares several event types as activating it
And a standing agent continues that procedure for a home
When an activation arrives for any one of those event types
Then it reaches that one standing agent
```

#### UC-PSA4: Editing the event list does not change the continuing agent

```gherkin
Given a standing agent continues a procedure for a home
When an event type is added to or removed from that procedure's declared subscriptions
Then the same agent continues the procedure
And no additional standing agent is started for it
And the agent listens to the amended set of event types
```

#### UC-PSA5: Overlapping subscriptions do not merge responsibilities

```gherkin
Given two distinct procedures each declare the same event type as activating them
And both answer the same home
When an activation for that event type arrives
Then each procedure's standing agent is activated
And neither procedure's responsibility is absorbed into the other
```

#### UC-PSA6: Procedure and home each identify a distinct agent

```gherkin
Scenario Outline: A difference on either identity dimension yields a separate agent
  Given two continuing responsibilities that differ in <dimension> and agree on the rest
  When an activation arrives for each of them
  Then each is continued by its own standing agent
  And an activation for one never reaches the other

  Examples:
    | dimension                                   |
    | procedure                                   |
    | home                                        |
    | home kind, for homes sharing one slug |
```

#### UC-PSA7: Concurrent activations produce one standing agent

```gherkin
Given no standing agent continues a procedure for a home
When two activations for that procedure and home arrive concurrently
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
Given an activation for a procedure and home arrives
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
Given a session carrying human lineage runs a procedure for a home on a computer
And no session under the system principal runs that procedure for that home there
When an activation for that procedure and home arrives on that computer
Then a standing agent is started under the system principal
And the activation is not delivered to the human-lineage session
```

#### UC-PSA13: A person, project, or platform activation starts its agent in that home without a company

```gherkin
Scenario Outline: The home is where the agent works
  Given no standing agent continues a procedure for <home> on the computer that emitted the event
  When an activation for that procedure and <home> arrives there
  Then a standing agent is started in <folder> under the system principal
  And an agent inspecting the session sees no company set on it

  Examples:
    | home         | folder                                 |
    | a person     | that person's folder                   |
    | a project    | that project's checkout                |
    | the platform | the platform's own checkout            |
```

#### UC-PSA14: A home absent on the emitting computer fails the activation

```gherkin
Given an activation for a procedure arrives naming a company, person, or project that is not registered on this computer
When the activation runner looks for that home's folder
Then no standing agent is started or woken
And an agent inspecting the activation record observes a failure naming the absent home
And no other home or computer takes the activation
```

#### UC-PSA15: A repeated activation reaches the agent once

```gherkin
Given a standing agent has received an event through an activation for a procedure and home
When an activation for the same event, procedure, and home arrives again
Then the agent does not receive the event a second time
And no second agent is started
```

#### UC-PSA16: A procedure declaring subject identity starts one agent per subject

```gherkin
Given a procedure declaring subject identity answers events of a home
And no agent of that procedure is bound to a subject in that home
When activations arrive there for events about two different subjects
Then two agents are started in that home under the system principal, one bound to each subject
And each receives only the activation about its own subject
```

#### UC-PSA17: A later event about the same subject reaches that subject's open agent

```gherkin
Given a procedure declaring subject identity keeps an open agent bound to a subject in a home
When an activation arrives for a further event about that subject
Then the activation is delivered to that agent
And no further agent is started
```

#### UC-PSA18: A later event about a subject revives that subject's closed agent with its own context

```gherkin
Given a procedure declaring subject identity started an agent bound to a subject in a home
And that agent's session has closed
When an activation arrives for a further event about that subject
Then that same session is revived and resumes its own transcript
And the activation is delivered to it
And no further agent is started
```

#### UC-PSA19: A closed subject-bound session that cannot resume is succeeded by a new agent

```gherkin
Given a procedure declaring subject identity started a session bound to a subject in a home
And that session closed without a transcript it could resume
When an activation arrives for a further event about that subject
Then a new agent bound to that subject is started in that home
And the activation is delivered to it
```

#### UC-PSA20: Concurrent activations about one subject produce one agent

```gherkin
Given a procedure declaring subject identity keeps no agent bound to a subject in a home
When two activations about that subject arrive concurrently
Then exactly one agent bound to that subject continues it afterwards
And both activations reach that agent
```

#### UC-PSA21: A subject-identity activation whose event names no subject fails

```gherkin
Given a procedure declaring subject identity answers events of a home
When an activation arrives for an event that names no subject
Then no agent is started or woken
And an agent inspecting the activation record observes a failure stating that the event names no subject
```

#### UC-PSA22: A procedure declaring home identity keeps one agent for the home

```gherkin
Scenario Outline: The default identity is unchanged by events about different subjects
  Given a procedure that <declaration> keeps a standing agent for a home
  When activations arrive for events about two different subjects in that home
  Then both are delivered to that one standing agent
  And no further agent is started

  Examples:
    | declaration                        |
    | declares no agent identity         |
    | declares the home agent identity   |
```

<!-- planned:procedure-agent-headless -->

#### UC-PSA23: An unattended agent stays out of the places people look at sessions

```gherkin
Scenario Outline: A person's ordinary view of sessions leaves an unattended agent out
  Given a procedure declaring itself unattended
  And an activation has started its agent
  When a person whose reach admits that agent's session <view>
  Then the agent's session is not shown

  Examples:
    | view                                            |
    | lists sessions without asking for every session |
    | opens the TUI sessions view                     |
    | looks for the session's thread in Discord       |
```

#### UC-PSA24: An unattended agent is shown when asked for

```gherkin
Scenario Outline: Asking for it shows an unattended agent to anyone whose reach admits it
  Given a procedure declaring itself unattended has an agent
  When a person whose reach admits that agent's session lists sessions <request>
  Then the agent's session is shown

  Examples:
    | request                              |
    | asking for every session             |
    | asking for the procedure's job       |
    | naming the session by its id         |
```

#### UC-PSA25: Attendance does not change which agent answers

```gherkin
Given a procedure declaring itself unattended keeps a running agent for a home
When a later activation for that procedure and home arrives
Then it reaches that same agent, as it would for an attended procedure
And that agent is still left out of the places people look at sessions
```

#### UC-PSA26: An agent started by hand is attended

```gherkin
Given a procedure declaring itself unattended answers company events
When an operator starts a session for that procedure and a company by hand
Then that session is shown wherever sessions are shown
```

<!-- /planned:procedure-agent-headless -->

### Cross-context references

- **integration** — hands this context an activation naming the procedure, the
  home, the agent identity the procedure declares, and the event it came from,
  only on the computer that emitted the event; it never starts or addresses a
  session itself.
- **config** — answers whether a company, person, or project is registered on
  the computer, and where its folder is.
- **identity** — owns the system-principal contract a standing agent runs
  under. This context decides nothing about identity and derives no
  authorization the identity contract does not publish.
- **context** — publishes the procedure, the event types it declares, the
  home kind it answers, and the agent identity it declares.

## Known caveats

- Standing is not remembering. A long-lived agent compacts; what it recovers
  afterward rests on durable state its procedure and domain own.

- The population of home-bound agents is bounded by the published procedures
  and the homes they serve. Subject-bound agents number one per subject their
  events concern; each lives as long as its procedure keeps it and returns only
  when a later event about its subject arrives. Workers an agent dispatches are
  a separate, bounded source of concurrency.

- Starting a standing agent by hand is available for a company home only; a
  person-, project-, or platform-home agent is started by an activation.
- A repeated activation is recognized only while the platform retains its
  delivery record.

- A subject-bound agent is started only by an activation; starting one by hand
  is not available.
- A subject-bound agent is found again only while the platform retains its
  session record. After that record is purged, a later event about the subject
  starts a new agent without the earlier context.

<!-- planned:procedure-agent-headless -->

- Attendance is recorded on a session when it is started. Changing a
  procedure's declaration affects the agents it starts afterwards; an agent
  already running keeps the attendance it started with.
- Sessions an unattended agent starts for its own work are attended.

<!-- /planned:procedure-agent-headless -->

## See Also

- docs/local/adr/0110-an-event-activated-procedure-runs-where-its-event-originated.md — why the agent runs on the emitting computer in the home its event's origin names.
- docs/local/spec/feature/agent_runtime/company-scoped-session-context.md — how a session's company and origin are established, carried, and published.
- docs/local/spec/feature/agent_runtime/coordinator-role-acquisition.md — the other singleton in this context: human-directed, one per project instance, enforced at an acquisition door rather than by activation.
- docs/local/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md — the schedule-driven sibling, which creates a session per run rather than keeping one standing.
