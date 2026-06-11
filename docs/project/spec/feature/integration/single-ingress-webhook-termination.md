---
id: project/spec/feature/integration/single-ingress-webhook-termination
type: spec
domain: software-development
scope: project
visibility: public
delivered_by:
  - webhook-ingress-service
description: One ingress computer terminates all external webhooks for the cluster —
  it is the only publicly reachable node, verifies and normalizes each inbound
  payload into a unified event, and relays it to the whole cluster unconditionally,
  so every other computer reacts by subscription without being publicly exposed.
---

# Single-Ingress Webhook Termination — Spec

## Required reads

- docs/global/software-development/spec/feature-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The behavioral contract for how external webhooks reach the cluster. Exactly one computer is the **ingress**: the single publicly reachable node for inbound webhooks (GitHub releases, provider events). It verifies each payload, normalizes it into the unified event shape, and relays it to the whole cluster — unconditionally, regardless of its own role or whether it would itself act on the event. Every other computer reacts by subscription, without being publicly exposed. The contract is stated in behavior, independent of HTTP server, bind mechanics, or message bus.

**Business value:** only one machine — ideally a cheap always-on appliance, not the maintainer's main computer — needs to be exposed to the internet. Every other machine, including ones behind their owners' home routers, still reacts to external events through the cluster. The public attack surface is one narrow, source-restricted endpoint instead of one per machine.

## Canonical fields

### Ingress contract

- **Single public node.** One computer is the ingress; it need not be the cluster master. No other computer accepts external webhooks.
- **Narrow reachability.** The ingress accepts forwarded traffic from the network boundary it is placed behind, and rejects other sources. It is not promiscuously open.
- **Verify, normalize, relay.** Every inbound payload is verified (provider signature), normalized into the unified event shape, then relayed to the whole cluster.
- **Unconditional relay.** The ingress relays every verified inbound event to the cluster regardless of its own configuration or whether it would itself act. The ingress decides nothing about the reaction.
- **Provider-agnostic.** The ingress terminates webhooks for any external provider; adding a provider does not change the ingress contract.

### Use cases

#### UC-SIT-1: External webhook reaches the cluster via the ingress

```gherkin
Given one computer is designated the ingress and is reachable at the network boundary
And another computer behind a home router is not publicly reachable
When an external provider sends a webhook
Then it arrives only at the ingress
And the ingress verifies it, normalizes it into the unified event shape, and relays it to the cluster
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
Given a payload arrives at the ingress without a valid provider signature
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
Then the same ingress terminates, verifies, normalizes, and relays each of them
And adding a new provider does not require a second public endpoint
```

### Cross-context references

- Owned by `integration` (`@docs/project/spec/domain/integration.md`); the inbound-boundary concern.
- The relay target and cluster delivery are the event-bus CLUSTER scope; the reaction is owned by subscribers, chiefly `reconciliation` (`@docs/project/spec/feature/reconciliation/channel-gated-self-update.md`).
- The topology decision (LAN bind, router source-restriction, single public node, unconditional relay) is a recorded architectural decision.
- Supersedes the v1 expression in `@docs/project/spec/feature/integration/deployment-version-fanout.md` (a bespoke deployment-only fan-out that relayed only when the receiver itself updated).

## Known caveats

- **Version-agnostic by construction.** Bind address, source-restriction mechanics, signature schemes, and bus technology live in the design layer and the delivering implementation, not here. The swap test applies.
- **The ingress is a single point of external-event intake.** While it is down, the cluster processes no external events but is not otherwise broken; the relay is stateless, so a second ingress can be added without redesign.
- **Reachability requires operator setup.** Port-forward at the boundary, the provider-side webhook registration, and the shared secret are operational prerequisites documented with the delivery, not part of this behavioral contract.

## See Also

- docs/project/adr/0028-single-lan-bound-ingress.md
