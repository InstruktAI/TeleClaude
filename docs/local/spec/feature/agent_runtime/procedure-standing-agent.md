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
activation for the same identity is queued for that agent and delivered at the
boundaries its procedure declares under
`local/projects/teleclaude/spec/feature/agent_runtime/procedure-event-delivery`.
A subject-bound agent whose session has closed is
revived with its own context before the activation is delivered to it. If its
transcript cannot be resumed, a later activation starts a new agent for that
same subject and home.

The procedure's ID is the procedure's part of that identity. Its declared
subscription patterns are its event membership and nothing more — there is no separate group identifier and no
group entity to register or manage. Two consequences follow: procedures whose
patterns overlap remain distinct responsibilities with distinct agents, and
editing a procedure's patterns changes what its agent listens to without
changing which agent it is.

<!-- planned-change:platform-installation -->

A standing agent works in its home on the computer that emitted the activating
event: a company's home folder, a person's folder, a project's checkout, or, for
the platform, the platform's own checkout. A named home that does not exist on
that computer fails the activation; the work is never moved to another home or
computer. An agent for a company home has the session's company set to that
company; an agent for a person, a project, or the platform has no company,
because location never supplies one
(`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`).

<!-- change:platform-installation -->

A standing agent works in its home on the computer that emitted the activating
event: a company's home folder, a person's folder, a project's checkout, or, for
the platform, the platform home. A named home that does not exist on
that computer fails the activation; the work is never moved to another home or
computer. An agent for a company home has the session's company set to that
company; an agent for a person, a project, or the platform has no company,
because location never supplies one
(`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`).

<!-- /planned-change:platform-installation -->

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

Existing sessions are reused only when they already run the same procedure for
the home under the system principal; a human-lineage session is never adopted
as a standing agent. Concurrent first activations for one agent identity still
establish one continuing session.

A standing agent is an ordinary scoped session. Standing confers no platform
role authority: it is not the integrator, the project coordinator, or a job
runner, and acquires none of their powers by continuing. An agent working in a
person's folder carries no human identity and acts as no person.

## Canonical fields

### Ubiquitous language

**Activation home**
: The one company, person, or project an activation concerns, as the event's origin names it by kind and slug, or the platform for an event whose origin is none.

<!-- planned-change:platform-installation -->

**Home folder**
: Where a standing agent works on the emitting computer — the company's home folder, the person's folder, the project's checkout, or the platform's own checkout.

<!-- change:platform-installation -->

**Home folder**
: Where a standing agent works on the emitting computer — the company's home folder, the person's folder, the project's checkout, or the platform home.

<!-- /planned-change:platform-installation -->

**Standing agent**
: The single live session that continues a procedure's work for one activation home.

**Activation**
: One delivery of a matched event to a procedure's standing agent — a start when none stands, a wake when one does.

**Subject identity**
: A procedure's declaration that each subject of its events within a home has its own agent, instead of one agent for the home.

**Subject-bound agent**
: The agent a procedure declaring subject identity keeps for one subject in one home — started by the first activation about that subject and reached by every later one, revived when its session has closed.

**Unattended agent**
: The agent of a procedure declaring that no person watches it. Its work is a run: it answers, works, and is recorded as any other agent of its procedure while its session is open, is never revived once that session has closed, and is left out of the places people look at sessions unless they ask for it (`local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle` UC-SL58).

### Use cases

#### UC-PSA1:

#### UC-PSA2:

#### UC-PSA3: Every declared event reaches the one standing agent

#### UC-PSA4: Editing the event list does not change the continuing agent

#### UC-PSA5: Overlapping subscriptions do not merge responsibilities

#### UC-PSA6: Procedure and home each identify a distinct agent

#### UC-PSA7: Concurrent activations produce one standing agent

#### UC-PSA8: The company and system origin survive every continuation

#### UC-PSA9: An activation that cannot be fulfilled is observable as a failure

#### UC-PSA10: A system-origin session already running the procedure for the company counts as standing

#### UC-PSA11: Starting an agent by hand is never refused

#### UC-PSA12: A human-lineage session running the procedure is not adopted

#### UC-PSA13: A person, project, or platform activation starts its agent in that home without a company

#### UC-PSA14: A home absent on the emitting computer fails the activation

#### UC-PSA15: A repeated activation reaches the agent once

#### UC-PSA16: A procedure declaring subject identity starts one agent per subject

#### UC-PSA17: A later event about the same subject reaches that subject's open agent

#### UC-PSA18: A later event about a subject revives that subject's closed agent with its own context

#### UC-PSA19: A closed subject-bound session that cannot resume is succeeded by a new agent

#### UC-PSA20: Concurrent activations about one subject produce one agent

#### UC-PSA21: A subject-identity activation whose event names no subject fails

#### UC-PSA22: A procedure declaring home identity keeps one agent for the home

#### UC-PSA23: An unattended agent stays out of the places people look at sessions

#### UC-PSA24: An unattended agent is shown when asked for

#### UC-PSA25: An open unattended agent answers as an attended one would

#### UC-PSA27: A closed unattended agent is not brought back

#### UC-PSA29: A procedure declaring no role starts no agent

#### UC-PSA26: An agent started by hand is attended

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

- Attendance is recorded on a session when it is started. Changing a
  procedure's declaration affects the agents it starts afterwards; an agent
  already running keeps the attendance it started with.
- Sessions an unattended agent starts for its own work are attended.

- A procedure's declared role is read when its agent is started. An agent
  already running, or revived, keeps the role it started with; a changed
  declaration reaches only the agents started afterwards, as attendance does.

## See Also

- docs/local/adr/0110-an-event-activated-procedure-runs-where-its-event-originated.md — why the agent runs on the emitting computer in the home its event's origin names.
- docs/local/spec/feature/agent_runtime/company-scoped-session-context.md — how a session's company and origin are established, carried, and published.
- docs/local/spec/feature/agent_runtime/coordinator-role-acquisition.md — the other singleton in this context: human-directed, one per project instance, enforced at an acquisition door rather than by activation.
- docs/local/spec/feature/agent_runtime/scheduled-agent-command-dispatch.md — the schedule-driven sibling, which creates a session per run rather than keeping one standing.
