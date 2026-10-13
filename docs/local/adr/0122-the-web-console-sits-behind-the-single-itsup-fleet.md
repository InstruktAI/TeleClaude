---
visibility: internal
number: 0122
date: 2026-10-13
description: The web console is reached through the one itsUP fleet on the ingress computer, which terminates public TLS and re-encrypts a pinned hop to a web service running natively on the master; webhooks stay on the ingress computer's daemon.
---

# The Web Console Sits Behind the Single itsUP Fleet — ADR

## Context

The operator web console needs a public address, TLS, and a path to the daemon
it acts on. The daemon it acts on is the one on the master computer, because
the console is the master's user interface the way the TUI is any computer's.
The fleet has one public entrance already: the ingress computer (a Raspberry Pi)
runs the one itsUP deployment, which terminates TLS with the certificates itsUP
manages and forwards the inbound webhook path to that computer's daemon on its
loopback listener. The master has no public exposure and runs no itsUP.

Two facts constrain the shape. A web service in a container cannot reach the
daemon's Unix socket: verified on 2026-09-27 (Docker Desktop 29.6.2) a bind-
mounted socket file is visible but `connect()` is refused, while a loopback TCP
server on the host is reachable. And the platform's inter-computer relay is a
request/response transport over Redis with no byte streams, so a terminal or a
preview cannot be carried from one computer to another through it.

## Decision

The console is reached through the existing itsUP fleet on the ingress computer,
and the daemon it serves is unchanged.

- The ingress computer's itsUP Traefik terminates public TLS for the console's
  host and re-encrypts to the master over a LAN hop pinned to one self-signed
  certificate that TeleClaude generates at install on the master. Nothing on that
  hop needs renewal, and the ingress computer connects only to that certificate.
- A web service, Python inside the `teleclaude` package and installed as a
  native service like the daemon, terminates that hop itself on a LAN port of
  the master that accepts only the ingress computer. It serves the console,
  authenticates people, and acts on the daemon over the Unix socket with carried
  identity, as the TUI does.
- Webhooks stay where they are: the ingress computer's daemon keeps
  `is_ingress_node`, its loopback listener and the inbound endpoints. The console
  path carries no webhook, and the master's daemon opens no listener for the
  console.
- The console runs where `computer.is_master` holds. No new computer flag marks
  it; a `web_console` configuration section overrides the port and the trusted
  proxy address only.
- The itsUP side — an HTTPS upstream with a pinned certificate for HTTP routes,
  the console's project declaration, the wildcard preview domain — is itsUP's
  own change (`https-host-upstream` in that repository).

## Alternatives Considered

- **A second itsUP deployment on the master.** Rejected: a second install root
  means a second projects-and-secrets repository pair, a second reconciler and
  stack, routing for one site split across two repositories, and no single CLI
  that drives both.
- **TLS passthrough by SNI from the ingress computer, terminated on the
  master.** Rejected: it moves public certificate management out of itsUP, onto
  a computer that runs no itsUP.
- **Relaying the console's traffic over the platform's Redis transport.**
  Rejected: the transport carries requests and responses, not byte streams, so
  the terminal and live previews cannot cross it.
- **Plain HTTP on the LAN between the ingress computer and the master.**
  Rejected: identity and session material would travel in clear across the
  home network.
- **Forwarding webhooks through the master as well, so one computer terminates
  everything.** Rejected: it adds the master as a dependency of webhook delivery
  for no gain, since the ingress computer already verifies and relays them to
  the whole cluster, and GitHub does not redeliver failed webhooks on its own.
- **A second ingress with the flag on the master as a webhook standby.**
  Rejected: it needs a health-checked failover route, a second listener and a
  spec allowing several ingress computers, to cover restart windows that a retry
  on the ingress computer's webhook route covers more simply.

## Consequences

- The ingress computer being down takes the console down; so does the master
  being down. Webhook delivery depends on the ingress computer alone, as before.
- itsUP gains one capability, an HTTPS upstream pinned to a certificate, usable
  by any service that terminates its own LAN hop.
- The certificate's public half is handed to the itsUP project once, and again
  only when the certificate is regenerated; regenerating it without that handoff
  makes the ingress computer refuse the hop until the handoff is repeated.
- The daemon learns nothing about TLS or HTTP from the console. The web service
  is one more socket client, and the console's identity path is governed by the
  identity specs the console delivers, not by a listener.
- The single-ingress webhook contract is untouched: one ingress computer, plain
  HTTP on loopback, signature authentication.
