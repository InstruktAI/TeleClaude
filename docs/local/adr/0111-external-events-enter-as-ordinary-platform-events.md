---
date: '2026-10-06'
description: 'A verified external request enters the platform as an ordinary event on the platform event stream, named <domain>.<name>, with the ingress as origin and the declaring home as subject. Producers that are ours speak one signed native protocol that TeleClaude relays without interpreting; GitHub and WhatsApp are adapters into the same shape. The source is declared in the home it concerns, the path is derived from that home, and every request is signed. The cluster.webhook relay is retired.'
number: '111'
visibility: 'internal'
---

# ADR-0111: External Events Enter as Ordinary Platform Events — ADR

## Context

ADR-0055 relays a verified webhook as a `HookEvent` on its own cluster pub/sub
channel, `cluster.webhook.<provider>`, and every computer re-dispatches it
through the hook contract matcher. That relay is separate from the platform
event stream. ADR-0105 and ADR-0109 gave every event on that stream its origin
and its subject, and procedures subscribe to the stream. A relayed webhook
reaches none of them.

Three further facts shaped the decision:

- Under ADR-0055 a source is declared under `hooks.inbound` in one project's
  configuration, with a freely configurable path, a normalizer key, an optional
  secret and an optional declared company. A source without a secret accepts
  unsigned requests.
- The first real external producer is a company's ERPNext sites. All
  ERP knowledge lives in the `erpnext-ops` repository, which owns the ERP
  documentation, CLI and procedures.
- GitHub and WhatsApp are protocols the platform itself consumes: the
  deployment handler reacts to GitHub, and conversation routing reacts to
  WhatsApp.

## Decision

- **One native inbound protocol.** A producer that is ours sends a signed
  request carrying a domain, a name and an opaque payload. TeleClaude verifies
  the request and relays it. It never parses or validates a domain payload, and
  it holds no domain vocabulary.
- **External events are ordinary platform events.** A verified request is
  published on the platform event stream at cluster scope, named
  `<domain>.<name>`, with the ingress computer as origin and the declaring home
  as subject. A consumer subscribes to `erp.invoice.paid` exactly as it
  subscribes to a platform event. External event names are not registered in
  the event catalog one by one.
- **The path names the subject, and the home declares the source.** A source
  is declared in the `teleclaude.yml` of the home it concerns, and its secret
  resolves from that home's own `.env`. The endpoint path is derived from the
  declaring home's kind and slug and is never configured. Only a home's own
  configuration opens an endpoint in its name.
- **Every request is signed.** A source without a secret cannot be declared,
  and a request without a valid signature is refused. There is no unverified
  mode.
- **GitHub and WhatsApp are adapters.** Each verifies with its own protocol's
  signature and translates into the same event shape. GitHub is declared by a
  project; WhatsApp is declared by the platform and has no subject, because its
  person is resolved per message by identity bindings.
- **The stream replaces the `cluster.webhook` relay.** Each computer delivers
  relayed GitHub and WhatsApp events from the stream to its own platform
  consumers. No second relay carries the same event.

## Consequences

**Positive:**

- One mechanism for every consumer: a procedure, an ad-hoc reader and the
  platform's own handlers all see external events in the platform's event
  shape.
- TeleClaude carries no knowledge of any business domain, and a new producer
  needs no TeleClaude change.
- The subject of an external event is authenticated, not asserted: only a
  sender holding that home's secret can produce an event in its name.
- No request is ever accepted unsigned.

**Negative:**

- The event catalog does not list external event names. A domain's own
  documentation states which names it emits.
- TeleClaude does not validate a domain payload. A malformed payload is its
  consumer's problem.
- The ingress computer must hold the configuration and `.env` of every home
  that receives external events, because verification happens there.
- A captured signed request can be replayed. Capturing one requires breaking
  the reverse proxy's TLS, and consumers own the idempotency of their own work.
- A computer running a version that only reads `cluster.webhook.*` receives no
  relayed webhooks. No computer has carried relayed webhook traffic, so none
  depends on that channel.

## Alternatives Considered

**Keep the `cluster.webhook` relay and also publish on the stream.** Rejected:
two relays carry the same fact, and each consumer must know which one it
reads.

**A generic signed source with a configurable signature header and encoding.**
Rejected: TeleClaude would adapt to every foreign protocol, so the producer's
format leaks into platform configuration. Producers that are ours speak the
platform's own protocol instead.

**A catalog event type per external event, published by its domain
repository.** Rejected: it requires domain repositories to publish types into
the platform catalog, a mechanism that does not exist, for no gain over relaying
the name.

**One generic catalog type that carries the domain event's name as a field.**
Rejected: consumers would subscribe to external events differently from
platform events and narrow on a payload field to find their own.

**Derive the subject from the payload, for example a GitHub repository to a
registered project.** Rejected: it needs remote-URL parsing, depends on what the
ingress computer has checked out, and breaks silently on a rename. The path
carries a subject the signature authenticates.

**Configurable paths with subject templates.** Rejected: paths can collide, and
one home's configuration could open an endpoint in another home's name.

**Refuse inbound names that use a platform event's namespace.** Rejected: only
a sender holding a home's secret can post at all, and such a producer is
trusted. A misnamed event is a visible, repairable configuration mistake.

## Status

Superseded in part by ADR-0114: the declaring home a relayed event concerns is
its `home`, and its `subject` names the one thing the event is about. The rest
of the decision stands.
