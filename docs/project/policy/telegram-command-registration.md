---
description: Rules for registering Telegram commands and keeping the command list consistent.
id: project/policy/telegram-command-registration
scope: project
type: policy
---

# Telegram Command Registration — Policy

## Rules

- Register all Telegram commands in the adapter startup flow.
- Each command must map to a concrete handler in `teleclaude/adapters/telegram_adapter.py`.
- Commands must be listed with the trailing space convention required by Telegram UX.

## Rationale

- Central registration prevents missing or partially wired commands.
- Users expect the command list to match actual behavior.

## Scope

- Applies to all Telegram commands in this repository.

## Enforcement

- New commands are rejected unless registered and wired end-to-end.
- Reviews must verify handler wiring and command list updates.

## Exceptions

- None. Emergency hotfixes still require registration.
