---
visibility: public
number: 78
date: 2026-09-02
description: Lifecycle dispatch records ownership directly and carries no time-bound reservation before or beside active ownership.
---

# ADR-0078: Remove time-bound dispatch reservations — ADR

## Status

Superseded in part by ADR-0096: prepare-artifact admission consults the
claiming group on a claimed todo. Superseded in part by ADR-0133: concurrent
driver starts for one todo on one computer are serialized by an in-process
critical section that records no state. Superseded in part by ADR-0135: for a
project on the GitHub store, the master records a start's claim before its
session exists. The retirement of time-bound dispatch reservations is unchanged
and remains accepted.

## Context

ADR-0035 retained a short-lived dispatch claim to bridge the interval between
selecting a lifecycle driver and recording its session as the Todo's
`active_runner`. ADR-0052 retained that claim alongside registry-authoritative
orchestrator dedup. The same reservation substrate later admitted a dispatched
diagnosis author around an artifact gate tied to lifecycle ownership.

The reservation introduced a second, expiring coordination state beside the
durable owner. It required acquisition, binding, release, expiry, cleanup, and
reconciliation paths, while artifact authorship and lifecycle ownership are
independent responsibilities. Lifecycle orchestration already has a durable
owner link, and assigned prepare authors already have their own capability
boundary.

## Decision

Todo lifecycle dispatch carries no time-bound claim, lease, or reservation.
Lifecycle start and in-process adoption record the driver session directly as
`active_runner`; session-end reconciliation clears that link. Prepare-artifact
admission never consults lifecycle ownership, and a diagnosis peer writes under
its prepare-author capability without delegated ownership or expiring authority.

Live-holder checks may still consume the Todo's `active_runner` and the session
registry according to their existing contracts. They do not create
pre-ownership state, and no replacement TTL, lock, reservation, inactivity
fallback, or dedup store is introduced.

## Consequences

- Artifact authorship no longer deadlocks behind a different lifecycle driver.
- The todos database no longer stores expiring dispatch rows or migration state
  for them.
- Autonomous and operator lifecycle starts have one fewer intermediate failure
  mode and one fewer cleanup obligation.
- A failed session start leaves no reservation to release; the ordinary start
  error remains the retry signal.
- The platform does not use a boot-gap TTL to serialize concurrent start
  attempts. Correct ownership begins when the spawned or adopted session is
  recorded as `active_runner`.
- Existing live-owner and registry checks remain responsible only for the
  already-established sessions their contracts describe.

## Alternatives Considered

- **Retain the generic reservation but remove the diagnosis lease.** Rejected
  because the expiring store would remain a second lifecycle coordination
  signal with acquisition, expiry, and reconciliation behavior.
- **Replace the reservation with a different lock or inactivity timeout.**
  Rejected because it preserves the same parallel ownership model under a new
  name.
- **Keep the foreign-`active_runner` artifact gate and delegate an exception.**
  Rejected because artifact authorship is a capability decision, not lifecycle
  ownership.
