---
id: 'project/policy/daemon-availability'
type: 'policy'
scope: 'project'
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
- After any change needing a restart, call `make restart` and observe success, or verify with `make status`.
- During instability, keep SIGTERM/socket monitoring enabled and retain logs under `/var/log/instrukt-ai/teleclaude/monitoring`.
- Verify key services after restart (API socket, API health/read endpoints, adapters).

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + verification is the safest minimal-downtime path.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, capture SIGTERM/socket monitoring logs before taking action.

## Exceptions

- None.
