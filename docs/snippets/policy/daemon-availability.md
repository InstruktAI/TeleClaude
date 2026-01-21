---
id: teleclaude/policy/daemon-availability
type: policy
scope: project
description: The TeleClaude daemon must stay up; restarts must be brief and verified.
requires: []
---

## Rule

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
- After any change, restart with `make restart` and verify with `make status`.
- Do not use `make stop` during normal development.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + verification is the safest minimal-downtime path.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement or checks

- Use `make restart` after changes and `make status` before reporting success.
- Review recent logs with `instrukt-ai-logs teleclaude --since 10m` if stability is in doubt.

## Exceptions or edge cases

- Use `make stop` only in emergencies when the daemon is crashing or unstable.
