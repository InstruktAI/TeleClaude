---
description:
  Only the master bot registers Telegram commands, and command names include
  trailing spaces.
id: teleclaude/policy/telegram-command-registration
requires:
  - teleclaude/architecture/telegram-adapter
scope: project
type: policy
---

## Rule

- Exactly one bot registers commands in a multi-bot supergroup.
- Set `telegram.is_master: true` on the master bot and `false` on all others.
- BotCommand definitions include trailing spaces to avoid `/command@botname` binding.

## Rationale

- Prevents duplicate command listings and inconsistent UX in Telegram clients.

## Scope

- Applies to all Telegram adapters in multi-bot deployments.

## Enforcement or checks

- Validate `telegram.is_master` configuration per host.
- Confirm trailing spaces in BotCommand names.

## Exceptions or edge cases

- None; multiple registrars indicate misconfiguration.
