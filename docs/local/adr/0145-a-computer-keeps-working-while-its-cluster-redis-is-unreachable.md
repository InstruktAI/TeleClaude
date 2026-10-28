---
visibility: public
number: 145
date: 2026-10-27
description: A computer starts and serves on its local Redis alone, forwards the cluster events it produced while the cluster Redis was unreachable once it is back, and queues sends that need another computer until it can reach it.
---

# A Computer Keeps Working While Its Cluster Redis Is Unreachable — ADR

## Context

The daemon refuses to start until the cluster Redis has answered once. That was
right while one shared Redis carried every event. With each scope on its own
Redis (ADR-0139), a computer's own work runs on its local Redis, and only what
other computers need from it depends on the cluster Redis: their views of its
sessions, the events they act on, requests between computers, and the sends the
master makes for others. A laptop that goes offline, or a cluster host that is
away, stops the computer entirely today, and what it produced meanwhile is lost.

## Decision

- **The local Redis is enough to run.** The daemon starts and serves with only
  its local Redis; the cluster connection reconnects on its own, and the
  installation status reports since when the cluster Redis is unreachable.
- **Cluster events are stored and forwarded.** A cluster event produced while
  the cluster Redis is unreachable is appended to an outbox stream on the local
  Redis and forwarded, in order, once it is reachable. Retained consumers on
  other computers then read it from their own positions; live views recover
  their current state on reconnect.
- **Requests between computers fail fast** while the cluster Redis is
  unreachable, with that as the reason.
- **Sends that need the master wait.** A person-facing send another computer
  asks of the master is queued in the same outbox and delivered once the master
  is reachable.

## Consequences

- Nothing a computer produces offline is lost; it arrives late.
- While the cluster host is away, the other computers lose their link to each
  other too, until it returns.
- The local Redis holds what is waiting to be forwarded, so it is durable state.

## Alternatives Considered

- **Require the cluster Redis to start.** Rejected: an offline computer stops
  working, though none of its own work needs another computer.
- **Drop cluster events while unreachable.** Rejected: other computers' retained
  consumers would miss facts they act on, such as a passed revision.
