---
visibility: public
number: 141
date: 2026-10-27
description: The local Redis is prepared while the previous release serves and applied in the stopped window, and a local Redis that cannot be set up leaves local events on the cluster Redis instead of failing the install.
---

# A Local Redis That Cannot Be Set Up Never Fails the Install — ADR

## Context

ADR-0140 made an install whose local Redis could not be configured fail with
the reason. The install act runs that setup in the stopped window, and an
install that fails there restores the previous release. The restored daemon
reads its installation source when it starts and admits the same revision
again, so a cause that persists — no sudo without a prompt, a Redis layout the
setup does not know, a Redis another program uses — stopped and restarted the
daemon on every cycle and the computer never upgraded.

Setting up the local Redis can also install a package, which takes minutes, and
the stopped window is downtime.

## Decision

The local Redis is set up in two steps. While the previous release serves, the
new release prepares it: it installs the Redis package when missing and checks
everything that can refuse, and may prompt for sudo from a terminal. In the
stopped window, before any migration, it applies it: it writes the Redis
configuration, restarts Redis, verifies it with its ACL user and writes the
variables that make the platform use it, never installing and never prompting.

Neither step fails the install. A refusal is logged with its reason and what
resolves it, and the computer keeps its local events on the cluster Redis; a
managed local socket that no longer answers is withdrawn so the daemon starts.

## Consequences

- A computer whose local Redis cannot be set up keeps installing every release
  and runs as it did before ADR-0139, at the network cost the split removes.
  Its install log and every daemon start name that state, and the installation
  inspector, which reads each install's log window, is where it surfaces.
- The stopped window holds no package install; a first install from a release
  that does not prepare the local Redis applies it only where Redis is already
  installed, and the next install prepares the rest.
- A setup that keeps refusing costs nothing beyond the log entry on each
  install.

## Alternatives Considered

- **Fail the install (ADR-0140).** Rejected: a persistent cause restarts the
  daemon every cycle and blocks every later release on that computer.
- **Remember a failed target and stop retrying it.** Rejected for this case: it
  still blocks the computer's upgrades until someone clears it, where falling
  back keeps them flowing.
