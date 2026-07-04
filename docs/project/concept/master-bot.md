---
description: 'The role of the master bot in a multi-computer Telegram supergroup.'
visibility: 'public'
---

# Master Bot — Concept

## What

Role of the master bot in a multi-computer Telegram supergroup.

1. **Command registration**: The master bot calls Telegram's `setMyCommands` API.

<!-- planned-change:telegram-dead-code-gutting -->

2. **User entrypoint**: Provides the autocomplete menu for `/new-session`, `/list-sessions`, etc.

<!-- change:telegram-dead-code-gutting -->

2. **User entrypoint**: Provides the autocomplete menu for `/list-sessions`, etc.

<!-- /planned-change:telegram-dead-code-gutting -->

3. **Status reporting**: Used for global system health checks.
4. **Consistency**: Keeps command definitions aligned with UX and adapter behavior.

## Why

Owns command registration only. Message routing and session ownership remain local to each bot.
