---
visibility: internal
number: 0124
date: 2026-10-14
description: A maintenance run that replaces the daemon stops it first, performs every owed step against the stopped process, and starts it last with a verified start, instead of ordering steps around a live daemon.
---

# Maintenance Replaces the Daemon Inside a Stopped Window — ADR

## Status

Superseded in part by ADR-0127: actions the maintenance registry declares to
run while the daemon serves run after the window's verified start.

Superseded in part by ADR-0130: a commit changes nothing live, so neither
commit-boundary nor on-demand maintenance replaces the daemon.

## Context

Commit-boundary and release maintenance ran while the daemon process kept
serving. Restarting the daemon was one owed action among others, placed by
precedence number; every step before it ran against the old process, and every
step after it against the new one. The daemon-availability policy said downtime
was not acceptable outside controlled restarts, and that sentence was read as
requiring the daemon to keep serving during maintenance.

A running daemon keeps the code it loaded at start while maintenance runs the
committed code from disk, so the old process meets whatever maintenance writes
before the restart. Steps that change shared state the live daemon reads — above
all the machine configuration in the platform home, which the daemon watches and
reloads — had to be ordered around the restart, and the configuration migration
gained a guard that asks the running daemon which version it can read before
storing anything. Each guard covered one writer. On 13 October a migration
stored a configuration version the serving daemon could not read, and the daemon
refused its own configuration for about five minutes until the restart step
replaced it. An audit then found the installer's agent-settings stage writing the
same document ahead of the guard, and installation migrations run by the
release updater write it before the advance is even recorded.

The fork was between keeping the daemon serving and continuing to order and gate
every writer around it, or treating a maintenance run as the controlled restart
it is and running it against a stopped daemon.

## Decision

A maintenance run that owes the daemon's replacement is a stopped-daemon window.
It waits for the daemon's accepted work to settle under the existing bounded
preparation, confirms the daemon has stopped, performs every owed step against
the stopped process in its dependency order, then starts the daemon and verifies
that it came back on the converged code. The run succeeds only on that
verification. The same window applies to on-demand maintenance when the
replacement is owed. A run that owes no replacement leaves the daemon serving.

## Consequences

- No step needs to know whether it runs before or after a restart, and no step
  asks a live process what it can read: inside the window there is no older
  reader. Writers that escaped the ordering, such as the installer's settings
  stage and installation migrations, stop being hazards for maintenance runs.
- The daemon is unavailable for the length of the run, which includes
  dependency synchronization and installation, not only the restart itself.
  Callers meet the existing retryable refusal; sessions, leased workers and the
  hook outbox outlive the stopped daemon as they outlive a restart.
- A run whose daemon holds work that never settles waits instead of proceeding,
  so a stuck preparation now delays maintenance as well as admission.
- Maintenance must outlive the stop of the daemon it replaces and must judge a
  start that it performs itself, so the window's start is bounded and its
  failure is recorded where an operator checking the daemon finds it.
- The configuration migration's reach guard stays for installation and
  registration performed while a daemon serves; it no longer protects
  maintenance runs that replace the daemon, which do not need it.
- A standalone installation run against a serving daemon is outside the window
  and keeps its own exposure to writers that precede the guard.

## Alternatives Considered

- **Keep the live daemon and gate every writer.** This preserves availability
  during maintenance, but each new writer of shared state must be found and
  ordered or gated, and the audit showed writers escaping. The guarantee lives
  in the completeness of a list nobody owns.
- **Make the daemon read newer documents.** An old process cannot interpret a
  shape defined after it was written; tolerant reading only covers new code
  reading old documents, which already exists.
- **Allow only the serving daemon to write its own documents.** Command-line
  writers and convergence of dependent repositories legitimately write
  configuration, so a single-writer rule would have broken existing contracts
  rather than closing the gap.
