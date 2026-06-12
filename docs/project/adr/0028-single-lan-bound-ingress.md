---
adr_status: 'accepted'
date: '2026-06-11'
description: 'A single ingress computer terminates all external webhooks for the cluster: it binds its webhook server to a LAN/router address (not localhost, not promiscuous), the router port-forwards public traffic to it, it restricts accepted sources to the router, normalizes each payload to a unified event, and relays it onto Redis at cluster scope. No other computer needs public exposure; the ingress need not be the master. This supersedes the v1 localhost-only bind and the self-update-gated deployment fan-out.'
number: '28'
visibility: 'public'
---

# ADR-0028: Single LAN-Bound Ingress Terminates External Webhooks for the Cluster — ADR

## Context

For the fleet to react to external events (a GitHub release, a provider webhook), some machine must be reachable from outside and receive the POST. v1 could not do this on two independent counts, either fatal:

1. **No inbound route existed.** The GitHub HTTP endpoint is data-driven from `hooks.inbound` in config, which defaults empty and is declared nowhere — GitHub's POST hit a 404.
2. **The API server bound only to `127.0.0.1`** (`API_TCP_HOST = "127.0.0.1"`, trusted hosts `{127.0.0.1, ::1, localhost}`). Nothing off-box could reach it; there was no LAN-bind knob, no source restriction, and no concept of an "ingress" computer.

Compounding this, the v1 deployment handler only published its cross-host fan-out _after_ deciding to update _itself_ — so a pure ingress (a Raspberry Pi that should not self-update) would receive the webhook and silently relay nothing.

The v2 integration design assumes the HTTP server is reachable but never says _which_ machine is public or _how_. The reachability topology is undocumented in both v1 and v2; it is the genuinely net-new piece.

## Decision

Designate a single **ingress computer** that terminates all external webhooks for the cluster. It need not be the master — a low-power always-on box (e.g. a Raspberry Pi) is ideal.

- **Bind to a LAN/router address, not localhost and not promiscuous.** The ingress webhook server binds to the machine's LAN address. The router port-forwards public inbound traffic to it. Accepted sources are restricted to the router's address, so the listener is reachable for legitimate forwarded traffic without being promiscuous (`0.0.0.0`).
- **Terminate, verify, normalize, relay.** The ingress receives webhooks for any project on any computer, verifies each (HMAC/signature per provider), normalizes the payload into the unified event shape, and **publishes it onto Redis at cluster scope** (event-bus CLUSTER visibility). It performs no domain reaction itself.
- **Distribution is subscriber-driven.** Every computer consumes the cluster-scoped event via its own subscription and reacts according to its own configuration (e.g. `reconciliation` self-updates by channel). No project-running computer needs public exposure; only the ingress does. The relay is unconditional — the ingress relays regardless of its own channel or whether it would itself act.
- **Provider-agnostic.** GitHub is one provider; the ingress is the cluster's single public webhook terminator for all of them.

This supersedes the v1 localhost-only bind and the self-update-gated `deployment:version_available` fan-out. The reaction (self-update) moves to `reconciliation` (ADR-0024); the ingress owns only termination and relay (`integration`).

## Consequences

**Positive:**

- Exactly one machine needs public exposure; the rest stay private and still react, via the cluster bus.
- The ingress can be a cheap always-on appliance distinct from the master, matching the real deployment (Raspberry Pi as ingress).
- The self-update-gating bug disappears: the ingress relays unconditionally and decides nothing.
- Source restriction to the router keeps the public surface narrow without `0.0.0.0`.

**Negative:**

- The ingress is a single point of failure for external-event intake. Mitigation is out of scope here; the cluster degrades to "no external events processed" (not "fleet broken") while the ingress is down, and a second ingress can be added later since the relay is stateless.
- Requires operator setup the docs must cover: router port-forward, the webhook secret, the LAN bind address, and registering the webhook URL at the provider.
- Binding off-localhost widens the trust boundary; the source-IP restriction and per-provider signature verification are the compensating controls.

## Alternatives Considered

**Every computer registers its own direct webhook.** Rejected: every machine would need public exposure and its own provider registration; the cluster bus already lets one receiver fan out to all.

**Bind promiscuously (`0.0.0.0`) and rely on signature verification alone.** Rejected: needlessly wide surface. LAN bind + router source-restriction + signature verification is defense in depth; signature-only is a single control.

**A public relay service outside the cluster.** Considered: a hosted endpoint that republishes onto the cluster bus would remove the home-network single-point-of-failure. Rejected for now (KISS / no external hosting dependency); revisited if the home ingress proves unreliable. The stateless-relay decision keeps this option open.
