---
visibility: public
number: 139
date: 2026-10-27
description: Every computer runs its own Redis for local events, the shared cluster Redis carries only events another computer needs, and each event type states the scope that decides where it is published.
---

# Each Event Scope Has Its Own Redis — ADR

## Context

ADR-0032 let one shared Redis serve both the local and the cluster scope and had
readers separate them by filtering on the envelope after reading. ADR-0013 had
put cross-computer state on the same Redis. Later the in-process local
subscriber path was removed, and the runtime notifications that path carried
moved to a stream on that shared Redis.

Every computer's consumers therefore read every event every computer produces,
and drop the ones that are not about their own computer only after downloading
them. On 2026-10-27 a laptop on mobile data used about 5 GB this way. The shared
Redis had sent 2.9 GB in 13.4 hours: 47,000 stream entries were acknowledged
832,000 times, one delivery per consumer group per computer, and the runtime
stream was read once per live consumer. Most of those events were a computer's
own minute tick and its own session source changes, which no other computer
reads.

The original three-scope design kept a mandatory local Redis on each computer
beside an optional cluster and public Redis.

## Decision

Each event scope has its own Redis. A local Redis on each computer carries local
events and is never reachable from another computer. The shared cluster Redis
carries only events a consumer on another computer acts on, together with the
cross-computer transport: requests, responses and heartbeats. The global scope,
for traffic between clusters, keeps its own endpoint and stays unbuilt until
there is traffic for it.

Every event type states its scope, and publication appends an event to the
Redis of its scope. Local is the default; a type is cluster only when a consumer
on another computer acts on it. A consumer reads from the Redis of every scope
its event types belong to.

The local Redis listens only on a Unix socket that only the computer's user and
the Redis service can open, and requires its own user and password. It runs
under the operating system's service manager, as the platform's Redis did
before.

## Consequences

- An event produced and consumed on one computer never crosses the network, so
  a computer's network use no longer grows with its own activity or with the
  number of consumers it runs.
- Every computer installs and runs a local Redis service; the platform does not
  start without it.
- A type wrongly stated local silently stops reaching other computers. The
  scope of a type is decided from the consumers that act on it, and a new
  cross-computer consumer changes its types' scope in the same change.
- A consumer whose types span both scopes reads two Redis instances and keeps
  separate progress on each.
- A computer on a release without this split reads every event from the shared
  Redis. While it remains, it no longer receives an upgraded computer's local
  events, and none of those are acted on by another computer.
- The local Redis is protected from other user accounts and from requests
  forged through a browser, not from a process running as the same user, which
  can read its credentials.

## Alternatives Considered

- **Keep one Redis and filter in the reader (ADR-0032).** Rejected: the filter
  runs after the download, which is the cost being removed.
- **A local durable log in the event database with in-process dispatch.**
  Rejected: it re-implements consumer groups, pending recovery and ordering that
  Redis streams already provide to the existing consumers.
- **Fewer events instead of a split.** Rejected: it removes symptoms one event
  type at a time and leaves every future local event on the network.
