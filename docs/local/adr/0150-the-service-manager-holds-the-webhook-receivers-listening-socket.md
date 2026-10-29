---
visibility: public
number: 0150
date: 2026-10-29
description: The ingress receiver's listening socket is held by its service unit and handed to the receiver process, so connections that arrive while the receiver restarts for a new release wait instead of being refused.
---

# The service manager holds the webhook receiver's listening socket — ADR

## Context

ADR-0148 runs the webhook receiver as its own service beside the daemon, so
intake survives daemon restarts. The receiver runs the active release's code,
so every install restarts it as well. While it restarts, nothing listens on its
port: the reverse proxy's forward is refused and a provider that does not
redeliver loses the event. The window is seconds per install instead of the
daemon's minutes, but it recurs with every install.

## Decision

- **The unit opens the port.** The receiver's listening socket is declared by
  its service unit (a systemd socket unit, a launchd socket declaration) and
  held by the service manager, which outlives the receiver process.
- **The receiver adopts it.** The receiver serves on the socket it is handed
  (systemd's passed descriptors, launchd's socket activation). Started outside a
  unit, it binds the port itself.
- **A restart queues instead of refusing.** Connections that arrive while the
  receiver restarts wait in the socket's queue and are served by the next
  receiver process.

## Consequences

**Positive:**

- An install no longer opens a window in which deliveries are refused; the
  receiver restarts for every release without losing intake.

**Negative:**

- A queued connection waits only as long as the provider's own request timeout;
  a receiver that takes longer to start loses it.
- Each service manager has its own handover, so the receiver carries an
  adoption path for each supported platform.

## Alternatives Considered

- **Keep the receiver running across installs.** Rejected: it would run an
  older release's verification and relay code than the rest of the computer.
- **Accept the restart window.** Rejected: intake becoming the trigger for work
  is the reason the receiver exists, and a window per install loses events with
  every release.
