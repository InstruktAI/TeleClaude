---
visibility: 'public'
description: 'One ingress computer terminates every external request for the cluster behind a local reverse proxy, verifies its signature, and relays it unconditionally as an ordinary platform event named <domain>.<name> whose source is the ingress, whose subject is the inbound source that received it and whose origin is the registered project, person or company that declared that source, so every computer and every consumer receives external events exactly as it receives platform events.'
---

# Single-Ingress Webhook Termination — Spec

## Required reads

- docs/global/sdlc/spec/feature-spec.md
- @docs/local/spec/domain/integration.md

## What it is

The behavioral contract for how external requests reach the cluster. Exactly
one computer is the **ingress**: the single node that accepts inbound requests
from outside the cluster. It verifies each request and relays it to the whole
cluster as an ordinary platform event, unconditionally, regardless of its own
role or whether it would itself act on the event. Every other computer reacts
by consuming the platform event stream, without being publicly exposed.

A relayed event has the shape of every other platform event. Its name is
`<domain>.<name>`, its source is the ingress computer, its subject is the
inbound source that received it, and its origin is the registered project, person or company that declared that
source. A consumer subscribes to a relayed event exactly as it subscribes to a
platform event, and never sees how the request arrived.

**Business value:** only one machine needs to be exposed to the internet, and
it can be any always-on computer. Every other machine, including ones behind
their owners' home routers, still reacts to external events through the
cluster. The public attack surface is one narrow, signature-authenticated
entrance instead of one per machine, and external systems become ordinary event
producers for every procedure and agent.

## Canonical fields

### Ingress contract

- **Single public node.** One computer is the ingress; it need not be the
  cluster master. No other computer serves the inbound endpoints.
- **Intake outlives the daemon.** Once the ingress turns on its receiver
  (`computer.ingress_receiver`), the receiver is a process of its own under its
  own service unit and the daemon serves no inbound endpoint; until then the
  daemon serves them on the same port. Changing the setting hands the port over
  in either direction before the daemon restarts to apply it. The
  receiver keeps receiving while the daemon restarts or an install stops it,
  and restarts itself when the active release changes or a validated machine
  configuration change needs a restart; an invalid change leaves it running on
  its configuration. On a computer that is no longer the ingress it exits
  before serving. Its
  service unit holds
  the listening socket and hands it to each receiver process, so a connection
  that arrives while the receiver restarts waits instead of being refused.
- **Narrow reachability.** The ingress serves plain HTTP on loopback only. A
  reverse proxy on the same computer is the public surface: it terminates TLS,
  restricts source and forwards only the inbound path prefix to the ingress.
  Any local reverse proxy satisfies the contract. The inbound endpoints
  authenticate each request by its signature alone and inherit no host-loopback
  trust. A request with an invalid signature receives a rejection response and
  is not relayed.
- **Verify, translate, relay.** Every request is verified against the secret of
  the home that declared its source, translated into the platform event shape,
  then relayed to the whole cluster. The endpoints, declarations, protocols and
  verification are owned by
  `@docs/local/spec/feature/integration/inbound-webhook-endpoint-framework.md`.
- **Unconditional relay.** The ingress relays every verified request regardless
  of its own configuration or whether it would itself act. The ingress decides
  nothing about the reaction.
- **Each delivery is relayed once per source.** A verified request is published
  through one atomic step on the cluster Redis that claims its delivery identity
  and publishes only when the claim is new. The identity belongs to the
  authenticated source (its protocol and declaring home): GitHub's delivery
  identifier for a GitHub request, and a digest of the verified request
  otherwise. A repeated delivery from the same source publishes nothing while
  its claim is retained and is still answered as accepted; two sources never
  share a claim.
- **Ordinary platform events.** A relayed event is published on the platform
  event stream under the event envelope contract
  (`@docs/local/spec/feature/event-catalog/event-envelope.md`):
  - its name is the source's domain followed by the source's event name,
    `<domain>.<name>`, and the event name may itself contain dots, such as
    `erp.invoice.paid`;
  - its source is the ingress computer, and it references no session, as for
    any event platform automation emits;
  - its subject is the inbound source that received it, which declares the
    protocol the ingress accepted it through: native, GitHub or WhatsApp. Two
    relayed events with the same name, home and data received through
    different sources remain distinguishable by it;
  - its origin is the registered project, person or company that declared the source, or none for a source the
    platform itself declares;
  - its data is what the producer sent.
- **No per-name registration.** Relayed event names are not entries in the event
  catalog. A domain's own documentation states which names it emits.
- **Platform consumers read the stream.** Each computer delivers every relayed
  event from the stream to its own platform handlers, once per computer per
  event, according to the protocol of the inbound source its subject names: an event relayed from the
  GitHub or WhatsApp endpoint as that provider's delivery, and an event relayed
  from a native endpoint as a native event, whatever its name.
  The ingress delivers to its own handlers the same way and does not also
  dispatch the request locally.
- **Provider-agnostic.** Adding a producer or a domain changes no part of this
  contract.

### Use cases

#### UC-SIT-1: An operator makes an external webhook available throughout a private cluster

```gherkin
Given an operator has connected an external provider to a TeleClaude cluster with private computers
When the provider sends a valid webhook
Then every running computer can receive the resulting external event through the cluster and react to it
```

#### UC-SIT-2: The ingress relays unconditionally

#### UC-SIT-3: Unverified payloads are rejected at the boundary

#### UC-SIT-4: Non-ingress nodes accept no external webhooks

#### UC-SIT-5: One ingress serves all providers and all projects

#### UC-SIT-6: A relayed event reads like a platform event

#### UC-SIT-7: A consumer subscribes to an external event by its name

#### UC-SIT-8: Identity headers on an inbound request reference no session

#### UC-SIT-9: An operator makes verified WhatsApp messages available to every cluster computer

```gherkin
Given an operator has enabled a WhatsApp source for a cluster with three computers
When a verified incoming message reaches that source
Then each computer's WhatsApp conversation handler receives the message once
```

#### UC-SIT-10: A native event keeps native treatment whatever its name

#### UC-SIT-11: Same name, subject and payload through two protocols stay distinct

### Cross-context references

- Owned by `integration` (`@docs/local/spec/domain/integration.md`); the
  inbound-boundary concern.

- The relay target is the platform event stream, whose
  envelope is owned by the event catalog
  (`@docs/local/spec/feature/event-catalog/event-envelope.md`). The reaction is
  owned by its consumers: procedures, a project's event-bound maintenance
  (`@docs/local/spec/feature/integration/event-bound-maintenance.md`) and
  WhatsApp conversation routing
  (`@docs/local/spec/feature/integration/whatsapp-inbound-conversation-routing.md`).

## Known caveats

- **The ingress is a single point of external-event intake.** While the server
  of its inbound endpoints is down (the daemon, or the receiver's unit once the
  receiver is turned on), the cluster processes no external events but is not
  otherwise broken; a provider that does not redeliver a failed request
  loses that event.
- **A restart is bounded by the provider's timeout.** A connection queued while
  the receiver restarts is lost if the receiver does not serve it before the
  provider gives up.
- **A former ingress keeps its receiver's units until its next start.** The
  receiver stops serving as soon as its computer's configuration says it is no
  longer the ingress; the units themselves are removed by the next start or
  install of that computer.
- **A claim is retained for a bounded time.** A delivery repeated after its claim
  has expired is relayed again.
- **Claims taken before claims named their source are not recognised.** A
  delivery claimed under the earlier identity, which named only the delivery,
  is relayed again if it is repeated within that claim's retention.
- **Relaying needs the cluster Redis.** While it is unreachable, the receiver
  cannot claim or publish, and a delivery fails.
- **A computer that is not running misses relayed events.** The stream is
  shared and bounded; a computer that comes back after its retained window has
  moved on does not replay the events it missed.
- **Reachability requires operator setup.** The local reverse proxy's route to
  the inbound path prefix, the source declaration in the receiving home with
  its secret in that home's `.env`, and the provider-side registration are
  operational prerequisites described in `docs/local/procedure/deploy.md`.

## See Also

- docs/local/adr/0028-single-lan-bound-ingress.md
- docs/local/adr/0055-proxy-fronted-ingress-reuse.md
- docs/local/adr/0111-external-events-enter-as-ordinary-platform-events.md
- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md
- docs/local/adr/0148-the-webhook-receiver-runs-beside-the-daemon-and-claims-each-delivery-before-relaying-it.md
- docs/local/adr/0150-the-service-manager-holds-the-webhook-receivers-listening-socket.md
