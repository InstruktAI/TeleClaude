---
description: Defines which service/daemon commands agents may run, which are conditional, and which are prohibited in this repo.
id: project/baseline/policy/agent-service-control
scope: project
type: policy
---

# Agent Service Control — Policy

## Rules

- **Allowed lifecycle commands:** `make restart`, `make status`.
- **Allowed checks:** `make status`, `instrukt-ai-logs teleclaude --since <window> --grep <str>`.
- **Allowed setup command:** `telec init` (docs sync/watchers + hooks).
- **Conditional (only when a restart is insufficient):** `make stop`, `make start`.
- **Disallowed (only for humans):** `bin/daemon-control.sh`, `bin/init.sh`, `launchctl`, `systemctl`, direct service bootout/bootstrap/unload/load.
- Never modify host-level service configuration without explicit approval.

## Rationale

- Limits accidental downtime and avoids unsafe service operations by automation.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- Review agent logs for prohibited commands; treat violations as incidents.

## Exceptions

- None; any exception requires explicit human approval.
