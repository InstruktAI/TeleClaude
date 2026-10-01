---
visibility: public
number: 0049
date: '2026-06-14'
description: 'Recurring-job ticks (scheduler.tick.*) are emitted by a loop mounted inside the always-on telec-daemon, not by an OS cron entry. The runtime is already a hard precondition for nearly all scheduled work, and source-owned cursors make scheduler durability non-load-bearing, so co-locating the emitter with the daemon collapses two failure domains into one and removes the cross-platform host-schedule install surface.'
---

# ADR-0049: Recurring-Job Ticks Emitted by an In-Daemon Loop, Not Host Cron — ADR

## Context

v2 recurring work — mining, sweeps, periodic notifications — needs a periodic trigger. The uniform pattern is a `scheduler.tick.*` Redis event that per-pillar listeners react to, each consulting its own source-owned cursor. The open question was where the tick _emitter_ lives: an OS cron entry (`* * * * * telec cron tick`) bridged into platform events, or a loop inside the always-on `telec-daemon`.

Two forces shaped the choice:

- The platform already runs one always-on, service-manager-supervised process — `telec-daemon`, kept alive by launchd/systemd KeepAlive, exposing a service-loop mount seam.
- Nearly all scheduled work is AI agent sessions that the runtime spawns and drives. A tick has no consumer that can act while the daemon is down.

## Decision

Emit `scheduler.tick.*` from a `scheduler` loop mounted on the `telec-daemon` service-loop seam, beside the reconciliation and ingress loops. The loop re-anchors each iteration to the next wall-clock minute. There is no OS cron entry, no `telec cron tick` CLI, and no per-platform install/uninstall of a host schedule. The `scheduler.tick.*` Redis events are the contract consumers depend on; the emitter sits behind that contract.

## Consequences

- The emitter shares the daemon's single liveness guarantee and KeepAlive supervision. Scheduler and consumers live or die together, so a tick is never produced for work that cannot run.
- The cross-platform host-schedule install surface (launchd plist vs Linux cron, add-on-install, remove-on-uninstall) disappears.
- Clock accuracy tracks the OS clock at minute granularity through wall-clock re-anchoring; a naive fixed-interval timer would drift and is precluded.
- Because the contract is the event and not the emitter, an alternative emitter (OS cron, systemd timer) can be reintroduced behind the same `scheduler.tick.*` events for a deployment that must fire jobs on a machine with no resident daemon. No such deployment exists today.
- Missed ticks across daemon downtime are not replayed by the emitter; correctness rests on source-owned, idempotent cursors — a listener consults "last ran at T" and processes the accumulated window — which is an existing invariant of the recurring-jobs pattern.

## Alternatives Considered

- **OS cron bridge** (`telec cron tick` plus one crontab entry per host). Rejected: it stands up a second supervised unit and a per-platform install/uninstall surface to buy resilience — firing while the daemon is down — that has no value here, because the tick's consumers are themselves daemon-mounted and idempotent cursors already absorb missed runs.
- **systemd timer with `Persistent=true`, or a durable scheduler (Temporal, Quartz-JDBC clustering).** Rejected: these solve multi-node exactly-once firing and durable missed-run catch-up. v2 does not coordinate recurring work across machines (multiple machines means multiple ticks, which is fine under source-owned cursors), and catch-up is already provided by the cursors, so the added machinery earns nothing.

## Status

Superseded by ADR-0054.
