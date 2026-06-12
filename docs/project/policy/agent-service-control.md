---
description: 'How agents operate the daemon: through the make targets (never raw host primitives); checkpoint-directed make install/restart are mandatory, never gated on human approval.'
visibility: 'public'
---

# Agent Service Control — Policy

## Rules

- **Agents operate the daemon through `make` targets, never through raw host primitives.** The `make` targets own every host-level service mechanic — including `bin/daemon-control.sh`'s launchd/systemd installation — internally.
- **Lifecycle and setup `make` targets are first-class agent commands:** `make restart`, `make start`, `make stop`, `make status`, `make install`, alongside `telec config wizard` and `telec projects init`. `make stop`/`make start` cover the case where a restart is insufficient.
- **Checkpoint-directed `make` targets are mandatory.** The checkpoint engine requires `make install` after setup changes and `make restart` after daemon-code changes. An agent never refuses, defers, or substitutes a checkpoint-directed `make` target on the basis of this policy — even when that target internally invokes `bin/daemon-control.sh`.
- **Checks:** `make status`, `instrukt-ai-logs teleclaude --since <window> --grep <str>`.
- **Do not hand-invoke host service primitives directly** — `bin/daemon-control.sh`, `launchctl`, `systemctl`, raw service bootout/bootstrap/unload/load. Route every service operation through the `make` targets, which wrap these safely. This is a use-the-sanctioned-wrapper rule, not an approval gate.

## Rationale

- The `make` targets are the safe, idempotent service interface; they encapsulate the platform-specific launchd/systemd mechanics so agents need no host-level judgement and no human gate for routine service operations. Routing through them limits accidental downtime while keeping checkpoint-required operations unblocked — a stale "human approval" gate that makes an agent refuse a required `make install`/`make restart` is itself the failure this policy prevents.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- An agent that refuses, defers, or substitutes a checkpoint-directed `make` target is in violation.
- Review agent logs for direct host-primitive invocation (`launchctl`, `systemctl`, raw `bin/daemon-control.sh`); route those operations through the `make` targets instead.

## Exceptions

- None.
