---
id: role/master-bot
type: role
scope: global
description: The role of the master bot in a multi-computer Telegram supergroup.
---

# Role: Master Bot

## Responsibilities

1. **Command Registration**: The master bot is the ONLY one that calls Telegram's `setMyCommands` API.
2. **User Entrypoint**: Provides the autocomplete menu for `/new-session`, `/list-sessions`, etc.
3. **Status Reporting**: Typically used for global system health checks.
4. **Consistency**: Keeps command definitions aligned with UX and adapter behavior.

## Configuration

- `telegram.is_master: true` in `config.yml`.
- Ensures commands use the "trailing space" pattern.

## Boundaries

- Message routing and session ownership remain local to each bot.
