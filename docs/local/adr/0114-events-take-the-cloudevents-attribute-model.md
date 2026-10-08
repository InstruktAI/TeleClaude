---
visibility: internal
number: 0114
date: 2026-10-07
description: Platform events take the CloudEvents attribute model internally — id, type, source, subject, time and data, with home, related and causationid as extensions — so subject names the one thing an event is about and home carries the registered home that ADR-0105 and ADR-0109 placed in subject; type names are namespaced by who owns them, and conformance to the CloudEvents specification waits for an external consumer.
---

# Events Take the CloudEvents Attribute Model — ADR

## Context

ADR-0105 gave every platform event an origin and a subject, and ADR-0109 gave
the subject three values. The subject named a registered home: the project,
person or company an event concerns. That answered whose an event is, but left
no attribute for what an event is about. A todo's lifecycle event, a session's
restart failure and a job's run outcome all named only their project, and the
thing itself lived in a payload field whose name differed per producer, or in
the uncontracted `entity` field.

Consumers being designed for the rebuilt event platform need that thing. A
platform alert keeps one open alert per thing and tells its recovery when that
thing recovers. An operational card names what it is about. Procedure
activation needs the home, and must not read it from the same field that names
the thing. Routing on payload fields is ruled out, because the payload is opaque
to routing.

Event type names did not say who owns a type. Platform types and business
domain types sat side by side (`system.*`, `job.*`, `domain.sdlc.*`), and
external events relayed through the ingress (ADR-0111) already used
`<domain>.<name>`.

CloudEvents is the industry vocabulary for these facts: `id`, `type`, `source`,
`subject`, `time` and `data`, extended by named attributes. Its `subject` is the
resource an event is about, within the context its source names.

## Decision

- **The attribute model is CloudEvents'.** Every platform event carries `id`,
  `type`, `source`, `subject`, `time` and `data`, plus the extensions `home`,
  `related` and `causationid`.
- **`source` is the emitting computer.**
- **`subject` is the one thing the event is about,** as a typed reference: the
  kind of thing and its identity.
- **`home` carries the fact ADR-0105 and ADR-0109 placed in the subject:** a
  registered project, person or company, none, or unknown, with a project's
  owner as resolved where the event happened. Reach and procedure homes key on
  `home`.
- **`related` references the other things involved,** each typed the same way.
  The session that emitted an event is one of them. **`causationid`** names the
  event that caused this one.
- **Type names are namespaced by owner.** `teleclaude.` prefixes what the
  platform itself emits. A published domain's name prefixes its events, and an
  external system's events enter through an inbound endpoint as events of their
  declared domain.
- **Conformance is deferred to the edge.** The platform uses the model and its
  names internally. The CloudEvents specification version attribute, URI-shaped
  sources and the standard serializations arrive as a serializer at the
  boundary when an external system consumes platform events.

## Consequences

- One attribute answers what an event is about, for every producer, so
  consumers keyed on the thing need no per-producer payload knowledge.
- Every producer must state a subject. Producers whose events used to carry
  only a home now name the thing as well.
- "Subject" means a home in the configuration vocabulary
  (`ConfigSubjectKind`, reach over a record's subject) and the thing in the
  event vocabulary. Inside events the home is `home`. Where identity reach
  reads an event, the event's home is the record's subject.
- Moving the home out of `subject` changes a shared shape. Under ADR-0026 the
  new attributes are added beside the old fields, and the old fields leave the
  wire only when no live node reads them.
- Renamed types reach older computers as names they do not know, which they
  ignore. A consumer on another computer that relies on a renamed type keeps
  receiving it only while its old name is still emitted.
- The platform carries no conformance work until it has an external consumer,
  and then the work is confined to one serializer.

## Alternatives Considered

- **Keep `subject` as the home and add a field for the thing.** Rejected: it
  keeps a private meaning for the industry's word, so every reader familiar with
  CloudEvents misreads it, and the uncontracted `entity` field shows how such a
  field drifts.
- **A field per kind of thing on the envelope** (a todo slug, a session id, a
  job name). Rejected: the envelope grows with every producer, and routing has
  to know each field instead of reading one typed reference.
- **Full CloudEvents conformance now.** Rejected: no external system consumes
  platform events, so the specification version attribute, URI sources and
  standard serializations would be maintained without a reader.
- **Keep the existing type names and add an owner attribute.** Rejected: a
  procedure subscribes to a type pattern, and a pattern like `erp.*` selects a
  whole domain only when the owner is the name's first segment.

## Status

Superseded in part by ADR-0118: the project, person or company an act happened in is the event's origin, stated with its emitting computer as its source; an event states no home, and the field named `home` carries the origin. The rest of the decision stands.
