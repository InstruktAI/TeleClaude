---
description: Guardrails for agent-run service control in this repo.
id: policy/agent-service-control
scope: project
type: policy
---

# Agent Service Control — Policy

## Rule

- **Allowed lifecycle command:** `make restart` and `make status` (use `make stop` and `make start` only when troubleshoooting daemon issues).
- **Allowed checks:** `make status`, `instrukt-ai-logs teleclaude --since <window> -g <str>`.
- **Disallowed (only for humans):** `telec init`, `bin/daemon-control.sh`, `bin/init.sh`, `launchctl`, `systemctl`, `make start`, `make stop`, direct service bootout/bootstrap/unload/load.
- **If health is unclear:** report status and ask for human direction; do not attempt recovery beyond `make restart`.
- Never modify host-level service configuration without explicit approval.
- Always report actions taken and current daemon status.

## Rationale

- Limits accidental downtime and avoids unsafe service operations by automation.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- Review agent logs for prohibited commands; treat violations as incidents.

## Exceptions

- None; any exception requires explicit human approval.
