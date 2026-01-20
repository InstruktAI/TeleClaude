---
id: policy/master-bot-registration
type: policy
scope: global
description: Policy for Telegram command registration in multi-computer setups.
---

# Master Bot Registration Policy

## Purpose
Prevents duplicate command entries and UI clutter in Telegram when multiple bots (from different computers) are in the same supergroup.

## Rules
1. **Single Registrar**: Only ONE computer (the master) registers commands with Telegram.
2. **Configuration**: Set `telegram.is_master: true` on the master and `false` on all others.
3. **Trailing Space Pattern**: Bot commands MUST include trailing spaces (e.g., `"new_session  "`) to prevent Telegram from appending `@botname` in autocomplete.
4. **Command Parity**: All bots MUST support the same command handlers even if they don't register them.
