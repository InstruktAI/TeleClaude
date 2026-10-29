---
date: '2026-06-22'
description: 'The v1 Python webhook ingress reuses the existing localhost API server behind a mandatory same-host reverse proxy instead of a dedicated LAN-bound listener: the proxy owns TLS, source restriction, and path routing, and webhook routes authenticate by HMAC alone with no loopback identity-trust. The verified event is relayed onto the cluster bus as a new cluster.webhook.* capability gated behind an ignorable feature-ID; the legacy deployment version_available fan-out remains as the expand-phase bridge and is retired only once the slowest channel carries the feature. Supersedes ADR-0028.'
number: '55'
visibility: 'public'
---

# ADR-0055: Proxy-Fronted Ingress Reuses the Localhost API Server — ADR

## Status

Superseded in part by ADR-0111: a verified request is relayed as an ordinary
event on the platform event stream rather than on `cluster.webhook.*`, and
every request is signed. The proxy-fronted loopback ingress and per-route
signature trust stand.

Superseded in part by ADR-0148: the webhook routes are served by a receiver of
their own beside the daemon, not by the daemon's localhost API server.

## Context

ADR-0028 designated a single ingress that binds its webhook server to a LAN/router address, with the router port-forwarding public traffic and in-process source restriction to the router. That decision assumed the daemon is itself the public surface.

The deployment reality is different: every ingress host runs a mandatory same-host reverse proxy (the operator's own — Traefik or the project's open-source proxy). The proxy is the public surface; it terminates TLS, restricts source, and routes paths. With a proxy in front, an in-process LAN bind and in-process source restriction duplicate what the proxy already owns, and binding the daemon off-localhost widens its trust boundary for no gain.

The existing API server (`teleclaude/api_server.py`) is already a FastAPI app served on a `127.0.0.1` listener, and the inbound webhook framework (`InboundEndpointRegistry`) already mounts verify→normalize→dispatch routes on an arbitrary FastAPI app. The capability that does not yet exist is the relay: a verified webhook is dispatched only to local contracts, never published onto the `cluster.*` bus, so no other node sees it.

The fleet is permanently multi-version (ADR-0026), so introducing a new cross-node channel must follow feature-ID capability gating (ADR-0027).

## Decision

- **Reuse the localhost API server behind a mandatory same-host reverse proxy.** The ingress mounts its webhook routes on the existing FastAPI app served on loopback; it never binds to a LAN or promiscuous address. The proxy owns TLS, source restriction, and path routing, forwarding only the webhook path prefix to the localhost endpoint. A node cannot be an ingress without a local proxy; there is no no-proxy / LAN-bind fallback.
- **Per-route trust.** Webhook routes authenticate by provider HMAC signature alone and inherit no loopback identity-trust, so co-locating them with the loopback-trusted control routes on one app adds no privilege path.
- **Relay as a feature-ID-gated capability.** The verified, normalized event is published onto `cluster.webhook.<provider>` on the cluster bus, gated behind an ignorable feature-ID (ADR-0027). Unaware nodes drop it cleanly. The ingress also dispatches the event locally; the bus drops its own echo at dispatch (ADR-0013 self-origin), so each node reacts exactly once. A publish failure fails the request so the provider retries — a verified event is never silently lost.
- **The legacy deployment fan-out is the expand-phase bridge.** The `version_available` Redis-stream fan-out is retained so nodes that do not yet carry the feature keep converging, and is removed only once the reconciliation capability map shows the slowest channel carries the feature.

This supersedes ADR-0028's LAN-bind and in-process source-restriction decision. The single-public-node, verify–normalize–relay, unconditional-relay, and provider-agnostic contract of ADR-0028 is retained.

## Consequences

**Positive:**

- No new listener, port, or bind surface; the ingress adds exactly one narrow, HMAC-authenticated path to an existing app, and the public surface is the proxy the operator already runs.
- The daemon stays localhost-only, so the trust boundary is not widened; source restriction and TLS live in the proxy where they belong.
- The relay rides the existing cluster bus and feature-ID gating, so it ships safely into a permanently multi-version fleet.

**Negative:**

- An ingress now has a hard prerequisite — a local reverse proxy — that the operator must install and configure (path routing for the webhook prefix, the provider secret).
- Webhook routes share an app and port with the loopback-trusted control API; the per-route HMAC-only trust must be preserved by every future change to the inbound path.
- The expand/contract discipline keeps the legacy fan-out alive until the capability map shows the slowest channel carries the feature.

## Alternatives Considered

**Dedicated LAN-bound ingress listener (ADR-0028 as written).** Rejected: with a mandatory same-host proxy, an in-process LAN bind and source restriction duplicate the proxy and widen the daemon's trust boundary for no gain; a separate listener also re-implements server lifecycle the API server already provides.

**Rebind the existing API server to a LAN address.** Rejected: that LAN-exposes the loopback-identity-trusted control API, not just the webhook routes.

**Remove the deployment fan-out at the same time as introducing the relay.** Rejected: the fleet is permanently multi-version (ADR-0026); removing the fan-out before the slowest channel carries the new relay strands un-upgraded nodes (ADR-0027 contraction gate). The fan-out is removed only after the capability map confirms universal carriage.
