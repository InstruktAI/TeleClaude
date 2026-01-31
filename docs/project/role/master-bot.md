---
description: The role of the master bot in a multi-computer Telegram supergroup.
id: project/role/master-bot
scope: global
type: role
---

# Master Bot — Role

## Purpose

Role of the master bot in a multi-computer Telegram supergroup.

## Responsibilities

1. **Command registration**: The master bot calls Telegram's `setMyCommands` API.
2. **User entrypoint**: Provides the autocomplete menu for `/new-session`, `/list-sessions`, etc.
3. **Status reporting**: Used for global system health checks.
4. **Consistency**: Keeps command definitions aligned with UX and adapter behavior.

## Boundaries

Owns command registration only. Message routing and session ownership remain local to each bot.
