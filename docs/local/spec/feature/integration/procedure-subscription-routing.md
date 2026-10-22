---
description: Platform events are matched, on the computer that emitted them, against the procedure subscriptions whose type patterns they fit and that answer their home's kind, and each match produces one activation naming the procedure and that home; publication is what makes a subscription live, and an event handed again is not activated twice.
visibility: internal
---

# Procedure Subscription Routing — Spec

## What it is

Procedure subscription routing is the step between a platform event and the
agent that answers it. It runs as one consumer of the platform event stream on
each computer (`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`),
interested in every event type, in events its own computer emitted, and in
events whose origin is known. There it matches each event it is handed against
the published procedure subscriptions and hands each match to the runtime
contract that owns standing agents, as one activation naming the procedure and
the event's origin. Routing decides nothing about whether an agent already
stands, and never starts or addresses a session itself. An event that matches
no published subscription produces no activation and is not a routing failure.

An event states its own source, origin and subject
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).
Routing reads them as stated and never constructs, replaces, or infers any of
them. Every computer reads the same stream; a computer that did not emit an
event does nothing with it, which is the normal case rather than a failure. An
event whose origin is unknown activates nothing anywhere.

A procedure subscribes with type patterns: an exact event type name, a prefix
of whole name segments followed by `.*`, or `*`. A pattern matches an event's
type exactly as the event catalog's one type-pattern matcher matches it, so
`erp.invoice.*` matches `erp.invoice.paid` and `erp.invoice.overdue.reminded`
but neither `erp.invoices.paid` nor `erp.invoice`, and `erp.*` matches every
event of the `erp` domain.

Every subscribed procedure declares the one kind of home it answers: company,
person, project, or platform. It matches an event of a subscribed type only
when the event's origin is of that kind, and a platform procedure matches events
whose origin is none. An origin is never converted to another kind: a project origin
does not reach its owning company's or person's procedures, and a company's
home does not reach its projects' procedures.

A published subscription is live for the reach its publication tier gives it:
a procedure published at global tier answers every home of its declared kind,
one published in a company's tier answers that company only, and one published
in a person's tier answers that person only. Publication is the registration:
nothing stands between an author declaring the events a procedure answers to
and those events reaching it.

An activation's identity is the event's id, the procedure, and the home.
Routing is handed an event once per event id; when its handling of an event is
interrupted and the event is handed again, every activation it already
produced for that event is found by its identity instead of produced again,
within the records the platform retains. When routing cannot submit an
activation, its handling of the event fails, and the consumer runtime retries
it and, when it keeps failing, parks and announces it.

Each activation also carries which agent the procedure declares answers its
events: one agent for the home, the default, or one agent for each subject of
the events. Routing reads that declaration from the published subscriptions as
it reads the patterns and the home kind, and hands it on unchanged; resolving
the agent it names belongs to the runtime contract that owns standing agents.
The activation's identity stays the event's id, the procedure, and the home,
because one event has one subject.

## Canonical fields

### Use cases

#### UC-PSR1:

#### UC-PSR2:

#### UC-PSR3:

#### UC-PSR4:

#### UC-PSR5:

#### UC-PSR7:

#### UC-PSR11:

#### UC-PSR12:

#### UC-PSR13:

#### UC-PSR14:

#### UC-PSR15:

#### UC-PSR16:

#### UC-PSR17:

#### UC-PSR18: An activation carries the attendance its procedure declares

#### UC-PSR19:

Routing carries the delivery declaration resolved by context along with the
existing subscription facts. This forwarding includes the context-resolved
attendance declaration. Runtime consumes it through its procedure
activation command and owns delivery under
`local/projects/teleclaude/spec/feature/agent_runtime/procedure-event-delivery`.
This keeps declaration interpretation with its owner
(`sdlc/policy/domain-ownership`).

### Cross-context references

- **event-catalog** — owns the event envelope this context reads, the one
  type-pattern matcher it matches subscriptions with, and the consumer runtime
  that hands it each event once, keeps its progress, and retries and parks its
  failures.
- **context** — publishes the procedure subscriptions this context matches
  against, with the patterns each declares, the home kind each answers, and the
  tier each is published at; this context never inspects the documentation
  corpus itself or decides what may be published into it.
- **agent_runtime** — receives the activation and owns everything after it:
  whether an agent already stands, where the home is and whether it exists on
  this computer, starting or waking the agent, and the principal and company it
  is bound to.

## Known caveats

- Matching establishes that a procedure's attention is due. It establishes
  nothing about whether a business mutation is necessary; a late or superseded
  event still reaches its agent and is reconciled by the activated procedure.
- Replay protection lasts as long as the platform retains the consumer's record
  of the event and the activation's operation and delivery records. A repeat
  arriving after they are pruned is routed as a new activation.
- A computer whose daemon does not run again before the stream drops an event it
  emitted misses that activation; no other computer stands in.
- A procedure published in a project's own tier is not part of the publication
  index this context matches against, so project homes are answered by
  procedures published at global tier.

## See Also

- docs/local/adr/0110-an-event-activated-procedure-runs-where-its-event-originated.md — why only the emitting computer activates.
- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why the home, not the subject, names whose an event is.
- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md — why routing is an independent consumer.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why an unknown origin is never read as none.
- docs/local/spec/feature/event-catalog/event-envelope.md — the source, origin and subject every event carries.
- docs/local/spec/feature/event-catalog/event-consumers.md — the consumer runtime and the type-pattern matcher.
