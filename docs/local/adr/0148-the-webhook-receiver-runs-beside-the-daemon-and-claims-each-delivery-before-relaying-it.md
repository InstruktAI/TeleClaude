---
visibility: public
number: 0148
date: 2026-10-28
description: The ingress's webhook receiver runs as its own service beside the daemon, so intake survives daemon restarts, and relays each delivery through an atomic claim on its delivery identity, so several receivers of one delivery publish it once.
---

# The webhook receiver runs beside the daemon and claims each delivery before relaying it — ADR

## Context

ADR-0055 placed the ingress's webhook routes on the daemon's own localhost API
server behind a mandatory same-host reverse proxy. The daemon restarts for every
install and every controlled restart, and while it does, the reverse proxy has
nothing to forward to: a provider's delivery in that window fails. GitHub does
not redeliver a failed delivery by itself, so the event is lost, and the
cluster's consumers never learn of it, although everything behind the ingress
already survives a restart by reading the cluster stream through consumer
groups.

External events are becoming the trigger for work rather than a convenience:
the lifecycle runner is to react to workflow changes instead of scanning every
project each minute, and a change made directly on GitHub reaches the active
computer only through its webhook. A single computer running alone has to keep
that intake through its own restarts; a fleet may want more than one receiver.

## Decision

- **The receiver is its own service.** On the ingress computer, the webhook
  receiver runs as a separate process under its own service unit, which the
  installation deploys and which outlives the daemon's restarts, as the local
  Redis does. It carries only what the ingress contract requires: verify the
  request against its declared source, normalize it, and relay it. It serves on
  loopback behind the same mandatory reverse proxy ADR-0055 requires; the daemon
  no longer serves the inbound paths.
- **Each delivery is claimed before it is relayed.** The receiver publishes a
  verified delivery onto the cluster stream through one atomic step on the
  cluster Redis that claims the delivery's identity and publishes it only when
  the claim is new. The identity is the provider's own delivery identifier where
  the provider supplies one, and a digest of the verified request otherwise. A
  second receipt of the same delivery, by the same receiver or another, finds the
  claim taken and publishes nothing.
- **More receivers need no new mechanism.** Because the claim is part of every
  relay, a fleet that has its reverse proxy deliver each request to several
  receivers gets each event published once, with no coordination between them.

This supersedes in part ADR-0055: its decision to serve the webhook routes from
the daemon's localhost API server. Its reverse proxy, per-route trust and relay
decisions are retained.

## Consequences

**Positive:**

- Intake no longer stops for daemon restarts or for an install's stopped window;
  the receiver restarts only to run a newly installed release, for seconds,
  outside that window, so the time in which a delivery can be lost shrinks from
  every restart and every migration to those brief restarts.
- A single computer is as robust as a fleet's ingress; a fleet's extra receivers
  are a reverse proxy setting, not new code.
- A provider retry or a duplicated delivery is relayed once.

**Negative:**

- The installation deploys and supervises one more service, and the reverse
  proxy's route moves from the daemon's port to the receiver's: an operator step
  on every existing ingress.
- A claim is kept for a bounded retention; a duplicate arriving after it has
  expired is relayed again.
- The receiver needs the cluster Redis to relay: while it is unreachable, a
  delivery fails as it did before this decision.

## Alternatives Considered

- **Keep the receiver in the daemon and ask GitHub to redeliver failed deliveries
  when the daemon starts.** Rejected: it recovers only GitHub's deliveries, only
  after the fact, and only for providers that offer redelivery.
- **Deliver each request to every computer and let them claim it, without a
  separate service.** Rejected as the foundation: a computer running alone has no
  second receiver, so its restarts still lose deliveries. The claim step this
  decision adopts keeps that fan-out available as an addition.
