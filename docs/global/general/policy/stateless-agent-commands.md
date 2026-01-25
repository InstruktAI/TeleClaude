---
id: general/policy/stateless-agent-commands
type: policy
scope: global
description: Policy for defining stateless AI agent commands.
---

# Stateless Agent Commands — Policy

## Rule

- Agent commands are atomic, explicit, and idempotent.
- Each command states prerequisites, performs the work, and ends with a verifiable outcome.

## Rationale

- Stateless commands are predictable, testable, and safe to re‑run.

## Scope

- Applies to all command definitions and operator guidance.

## Enforcement

- If a command requires setup, include it explicitly in the command flow.
- If sequencing is required, use orchestration/state machines rather than hidden steps.

## Exceptions

- None.
