---
visibility: internal
number: 0105
date: 2026-09-29
description: A platform event states facts about itself — its origin and its subject, with a project subject's owner as known where it happened — and who may receive it is derived from that subject on the receiving computer; producers never decide or validate an audience.
---

# Event Access Follows the Subject Its Producer States — ADR

## Context

Consumers of the platform event stream need to know whose an event is. Agent
subscriptions need to wake only principals entitled to it, procedure activation
needs to start a standing agent in the right home, and notification listings
need to show each principal only what it may see. The stream carried only the
computer an event was emitted on. The one existing scoping mechanism stamped a
company onto inbound webhook events alone, so scope depended on which producer
happened to set it.

Several forces constrain the answer. The fleet is a set of computers that don't
know each other's projects, persons, or companies, and events travel between
them on a shared stream. Most events come from platform automation, which runs
in no home but always acts on something that belongs to one. The producers are
the platform's own code; untrusted input enters only where agents or external
parties call in.

## Decision

- **A producer states facts about the event, never about its consumers.** It
  states its **origin**: the computer, plus the emitting session and that
  session's registered home when a session emitted it. It also states its
  **subject**: the registered project, person, or company the event is about,
  or none when the event is about the platform itself. A project subject also
  carries its owner (company, person, or none) as resolved on the emitting
  computer.
- **Access follows the subject, not the origin.** Data is sensitive for what it
  is about, not for which process emitted it. Automation uses the home of what
  it acted on as the subject.
- **Receipt is decided on the receiving computer,** from the receiving
  principal's reach and the event's subject. The producing side never filters
  and never names an audience.
- **Emission is by contract.** Producers set origin and subject as part of
  their emission invariant, and emission validates and refuses nothing on their
  basis. Runtime validation happens only where untrusted input enters.
- **Each event carries its own subject.** An event type declares what its
  events are about. A type is not pinned to one kind of home, because one event
  type can concern homes of different kinds.

## Consequences

- Every producer must state a subject. An event whose subject is missing or
  wrong isn't rejected. Once access is enforced, it degrades silently to
  admin-only visibility.
- Carrying the owner lets a receiving computer that doesn't know a project
  still admit that project's owning company members or owning person. The
  owner is a fact as of emission; a later ownership change doesn't rewrite
  events already emitted.
- Adding origin and subject changes a shared shape, so it evolves additively
  under ADR-0026. Events from nodes that predate it read as having no subject.
- Scoping on the stream is uniform across producers, so no producer-specific
  scope mechanism is needed. Such a mechanism is superseded where its consumers
  move onto the stream.
- The actor who triggered an event is not a base fact. Where the actor is the
  event's own fact, it stays in that type's payload.

## Alternatives Considered

- **The producer declares the event's scope or audience.** Rejected: a producer
  can't know who, on which computer, will consume an event. Deciding it at
  emission couples producers to consumers, and the coupling breaks across
  computers that don't know each other's homes.
- **Access follows the origin.** Rejected: most events come from automation that
  runs in no home. Origin-based access would make them admin-only, so a member's
  agent could never observe its own todo's lifecycle.
- **One fixed scope kind declared per event type.** Rejected: one event type can
  concern homes of different kinds. A session event concerns the session's home,
  which may be a project, a person, or a company.
- **Validate subjects against registries at emission.** Rejected: the emitting
  computer can't speak for other computers' registries. Refusing at emission
  would drop true facts, while validation belongs where untrusted input enters.
- **Carry a filesystem path as the origin.** Rejected: a path means something on
  one computer only. A registered slug plus the computer is portable.

## Status

Superseded in part by ADR-0109: an event's subject is a registered home, none
when it concerns no registered home, or unknown when it cannot be established,
and events from computers that predate the subject read as unknown. The rest of
the decision stands.

Superseded in part by ADR-0114: the registered home an event concerns is its
`home`, and its `subject` names the one thing the event is about. Access
follows the home. The emitting session is a related reference, and an event
names no origin home.
