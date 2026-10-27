---
visibility: public
number: 143
date: 2026-10-27
description: Every computer runs a local Redis instance of TeleClaude's own, under a unit the installation owns, instead of reconfiguring the operating system's Redis; the computer that hosts the cluster Redis gets one too.
---

# TeleClaude Runs Its Own Local Redis on Every Computer — ADR

## Context

ADR-0139 gave every computer a local Redis and ADR-0140 made the installer
configure the operating system's Redis as that local Redis, except on the
computer that hosts the cluster Redis. Taking over a Redis the operating system
provides meant reconfiguring a service other programs may use, telling apart
the Redis layouts of each Linux family, changing the service's group on Linux,
and needing sudo to edit system files. On one computer of the fleet the Redis
package was absent and the port its default configuration uses belonged to a
reverse proxy, so the operating system's Redis could not start there at all.

The exception for the cluster host was wrong. Every other computer reads what
is on the cluster Redis and discards what is not about itself only after
downloading it, so the cluster host's local events on the cluster Redis still
cross every other computer's network.

## Decision

- **Every computer runs its own local Redis instance**, the cluster host
  included. It is a Redis server process TeleClaude starts with its own
  configuration and data directory in the platform home, listening only on a
  Unix socket only the TeleClaude user can open, with its TCP port and default
  user off and one ACL user whose password lives in the machine environment.
- **The installation owns its unit.** A user agent on macOS and a system unit
  running as the TeleClaude user on Linux keep it running. Stopping the daemon
  leaves it running, because commands and periodic jobs publish local events
  while the daemon is down.
- **It never touches another Redis.** An existing Redis on the computer,
  whoever uses it, stays as it is. Only the Redis server binary is needed; when
  the install adds the operating system's Redis package to get it and that
  package starts a service of its own, that service is disabled.
- **Setup keeps the two steps of ADR-0141**: the binary is installed while the
  previous release serves, and the instance is configured, started and verified
  in the stopped window.

## Consequences

- The installation owns one more unit, outside the set that stopping the daemon
  brings down.
- Setting up the local Redis needs no sudo on macOS, and on Linux only for
  installing the package and deploying the system unit.
- A computer set up by the earlier installer carries a block it added to the
  operating system's Redis configuration; the install removes that block, since
  nothing reads that Redis as the local Redis any more.
- The cluster host keeps its own events off the cluster Redis like every other
  computer.

## Alternatives Considered

- **Configure the operating system's Redis (ADR-0140).** Rejected: it takes over
  a service others may use and depends on each distribution's layout.
- **A second instance from the operating system's service template.** Rejected:
  Debian ships one, macOS's Homebrew services and other Linux families do not.
- **A container.** Rejected: it adds a container runtime as a dependency of
  every computer.
