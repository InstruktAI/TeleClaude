---
visibility: public
number: 140
date: 2026-10-27
description: A computer that hosts the cluster Redis, or has no local Redis configured, keeps its local events on the cluster Redis instead of refusing to start, and the installer sets up the local Redis everywhere else.
---

# A Computer Without Its Own Local Redis Keeps Local Events on the Cluster Redis — ADR

## Context

ADR-0139 gave every computer its own local Redis and made the platform refuse
to start without one. Two cases did not fit that.

A computer that hosts the cluster Redis on itself already keeps every event it
produces on the computer: the cluster Redis is its local Redis in all but name.
A second Redis there would carry the same traffic over the same loopback.

The edge channel installs a release by itself on computers nobody is watching.
Each of them would install a release that refuses to start before its local
Redis exists, and an install that has run its configuration migration cannot
roll back.

## Decision

The local scope uses the computer's local Redis when one is configured, and the
cluster Redis otherwise. A computer whose configuration names no local Redis
logs that at startup and carries its local events on the cluster Redis, as it
did before ADR-0139.

The installer configures the local Redis on every computer whose cluster Redis
is on another computer, and verifies it answers before the install continues.
It configures none on a computer that hosts the cluster Redis, keeps a local
Redis the operator configured that answers, and refuses, naming what to set
instead, to take over a Redis that another program uses.

## Consequences

- A computer that installs the release runs with the split as soon as the
  install completes; one whose installer could not configure the local Redis
  fails its install with the reason, rather than starting without the split.
- The computer that hosts the cluster Redis keeps its events on that Redis and
  needs no second one. Its local events reach the network only if other
  computers read its Redis, as before.
- The platform still starts with no local Redis configured, so a configuration
  that loses its local Redis setting silently costs network traffic again;
  the startup log is where that shows.
- The installer changes the operating system's Redis configuration, and on
  Linux its service's group, so it needs the privileges the installer already
  uses for system packages.

## Alternatives Considered

- **Refuse to start without a local Redis (ADR-0139).** Rejected: every
  unattended computer that installs first would stop serving, and the computer
  hosting the cluster Redis would need a Redis it gains nothing from.
- **A TeleClaude-owned Redis instance beside the operating system's.**
  Rejected for now: it adds a service the installation must own, start and stop
  apart from the daemon, where the operating system's Redis is already present
  on every computer and unused by anything else on the computers this serves.

## Status

Superseded in part by ADR-0141
