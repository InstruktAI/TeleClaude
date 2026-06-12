---
visibility: 'public'
number: '41'
date: '2026-06-12'
adr_status: 'accepted'
description: 'Agents operate the daemon through the make targets; routine service operations are not gated on human approval.'
---
# Agents Own Daemon Lifecycle via Make Targets — ADR

## Context

The Agent Service Control policy predated the checkpoint engine. It marked
`bin/daemon-control.sh`, `launchctl`, and `systemctl` as "only for humans" and
required "explicit approval" before modifying host-level service configuration.

Since then the checkpoint engine (`teleclaude/constants.py`
`CHECKPOINT_FILE_CATEGORIES`) made `make install` (after setup changes) and
`make restart` (after daemon-code changes) **blocking** required actions for
agents — and the `make` targets forward their host-level mechanics to
`bin/daemon-control.sh` internally (the `make start/stop/restart/status →
daemon-control.sh` path documented in the daemon-runtime design). The two
rule-sets contradicted each other: an agent reading the policy would refuse a
checkpoint-mandated `make` target because it transitively invokes a command the
policy called human-only.

## Decision

Agents operate the daemon exclusively through the `make` targets — `restart`,
`start`, `stop`, `status`, `install` — which own every host-level service
mechanic, including `bin/daemon-control.sh`'s launchd/systemd installation,
internally. Checkpoint-directed `make` targets are mandatory; no policy gates a
routine service operation on human approval. Direct hand-invocation of raw host
primitives (`bin/daemon-control.sh`, `launchctl`, `systemctl`) stays discouraged
in favour of the `make` wrappers — as a use-the-sanctioned-wrapper convention,
not an approval gate.

## Consequences

- The failure mode where an agent refuses a checkpoint-mandated `make
  install`/`make restart` on policy grounds is removed; the checkpoint engine and
  the service-control policy now agree.
- `bin/daemon-control.sh` is correctly scoped as the `make` targets' internal
  implementation detail rather than a forbidden command.
- Agents now carry responsibility for daemon lifecycle operations that were
  nominally reserved for humans. A faulty change deployed via `make
  restart`/`make install` reaches the running service, so the safeguard shifts
  from a policy-level approval gate to code review plus the checkpoint engine's
  own post-restart verification (`make status`).
- There is no longer a human checkpoint immediately before a service restart;
  deploy discipline (restart only committed, reviewed changes) becomes the
  controlling safeguard, not policy text.

## Alternatives Considered

- **Keep the human-approval gate and exempt only the `make` targets.** Rejected:
  it preserves the contradiction surface — an agent must still reason about
  whether a given `make` target transitively touches a "human-only" command — and
  re-introduces refusal risk.
- **Forbid agents from daemon lifecycle entirely; humans run all restarts.**
  Rejected: it contradicts the checkpoint engine's design, which makes
  restart/install agent-required after the changes that need them, and would
  stall autonomous operation on every daemon-code or setup change.