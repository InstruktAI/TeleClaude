---
visibility: 'public'
description: 'One ingress computer terminates every external request for the cluster behind a local reverse proxy, verifies its signature, and relays it unconditionally as an ordinary platform event named <domain>.<name> with the ingress as origin and the declaring home as subject, so every computer and every consumer receives external events exactly as it receives platform events.'
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
`<domain>.<name>`, its origin is the ingress computer, and its subject is the
home that declared the source. A consumer subscribes to a relayed event exactly
as it subscribes to a platform event, and never sees how the request arrived.

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
- **Narrow reachability.** The ingress serves plain HTTP on loopback only. A
  reverse proxy on the same computer is the public surface: it terminates TLS,
  restricts source and forwards only the inbound path prefix to the ingress.
  Any local reverse proxy satisfies the contract. The inbound endpoints
  authenticate each request by its signature alone and inherit no host-loopback
  trust.
- **Verify, translate, relay.** Every request is verified against the secret of
  the home that declared its source, translated into the platform event shape,
  then relayed to the whole cluster. The endpoints, declarations, protocols and
  verification are owned by
  `@docs/local/spec/feature/integration/inbound-webhook-endpoint-framework.md`.
- **Unconditional relay.** The ingress relays every verified request regardless
  of its own configuration or whether it would itself act. The ingress decides
  nothing about the reaction.
- **Ordinary platform events.** A relayed event is published on the platform
  event stream at cluster scope under the event envelope contract
  (`@docs/local/spec/feature/event-catalog/event-envelope.md`):
  - its name is the source's domain followed by the source's event name,
    `<domain>.<name>`, and the event name may itself contain dots, such as
    `erp.invoice.paid`;
  - its origin is the ingress computer, with no emitting session and no origin
    home, as for any event platform automation emits;
  - its subject is the home that declared the source, or none for a source the
    platform itself declares;
  - its payload is what the producer sent.
- **No per-name registration.** Relayed event names are not entries in the event
  catalog. A domain's own documentation states which names it emits.
- **Platform consumers read the stream.** Each computer delivers relayed GitHub
  and WhatsApp events from the stream to its own platform handlers, once per
  computer per event. The ingress delivers to its own handlers the same way and
  does not also dispatch the request locally.
- **Provider-agnostic.** Adding a producer or a domain changes no part of this
  contract.

### Use cases

#### UC-SIT-1: External webhook reaches the cluster via the ingress

```gherkin
Given one computer is designated the ingress and is reachable at the network boundary
And another computer behind a home router is not publicly reachable
When an external provider sends a webhook
Then it arrives only at the ingress
And the ingress verifies it, translates it into the platform event shape, and relays it to the cluster
And the non-public computer receives the event through the cluster and reacts
```

#### UC-SIT-2: The ingress relays unconditionally

```gherkin
Given the ingress is a low-power appliance that would not itself act on a given event
When it receives and verifies that event
Then it relays the event to the cluster anyway
And the relay does not depend on the ingress's own role, channel, or whether it would act
```

#### UC-SIT-3: Unverified payloads are rejected at the boundary

```gherkin
Given a payload arrives at the ingress without a valid signature
When the ingress verifies it
Then verification fails
And no event is relayed to the cluster
And the sender receives an appropriate rejection response
```

#### UC-SIT-4: Non-ingress nodes accept no external webhooks

```gherkin
Given a computer is not the designated ingress
When an external webhook is directed at it
Then it does not serve as a public webhook endpoint
And the cluster's single public surface remains the ingress alone
```

#### UC-SIT-5: One ingress serves all providers and all projects

```gherkin
Given the ingress is configured to receive webhooks
When events arrive for different external providers or different projects
Then the same ingress terminates, verifies, translates, and relays each of them
And adding a new provider does not require a second public endpoint
```

#### UC-SIT-6: A relayed event reads like a platform event

```gherkin
Given a company home declares a native source
And its producer sends a signed request with domain "erp", name "invoice.paid" and a payload
When an agent consuming platform events on any computer receives the relayed event
Then the event is named "erp.invoice.paid"
And its origin names the ingress computer and no emitting session
And its subject is that company
And its payload is the one the producer sent
```

#### UC-SIT-7: A consumer subscribes to an external event by its name

```gherkin
Given a consumer subscribes to the event name "erp.invoice.paid"
When the ingress relays a verified request whose domain is "erp" and whose name is "invoice.paid"
Then the consumer receives it exactly as it receives a platform event of a subscribed name
And nothing about the inbound request is visible beyond the event itself
```

#### UC-SIT-8: Identity headers on an inbound request do not become the event's origin

```gherkin
Given a signed inbound request also carries headers that name a caller session
When the ingress relays it
Then the relayed event names no emitting session and no origin home
```

#### UC-SIT-9: Every computer's platform handlers receive a relayed provider event once

```gherkin
Given three computers, one of which is the ingress
When the ingress relays a verified WhatsApp message
Then each of the three computers delivers that message to its own WhatsApp conversation handling once
And the ingress does not deliver it a second time from the request itself
```

### Cross-context references

- Owned by `integration` (`@docs/local/spec/domain/integration.md`); the
  inbound-boundary concern.
- The relay target is the platform event stream at cluster scope, whose
  envelope is owned by the event catalog
  (`@docs/local/spec/feature/event-catalog/event-envelope.md`). The reaction is
  owned by its consumers: procedures, the deployment handler
  (`@docs/local/spec/feature/integration/github-webhook-normalization.md`) and
  WhatsApp conversation routing
  (`@docs/local/spec/feature/integration/whatsapp-inbound-conversation-routing.md`).
- Supersedes the v1 expression in
  `@docs/local/spec/feature/integration/deployment-version-fanout.md` (a bespoke
  deployment-only fan-out that relayed only when the receiver itself updated).

## Known caveats

- **The ingress is a single point of external-event intake.** While it is down,
  the cluster processes no external events but is not otherwise broken; the
  relay is stateless, so a second ingress can be added without redesign.
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
