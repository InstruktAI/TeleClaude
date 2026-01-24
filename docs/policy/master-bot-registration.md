---
id: policy/master-bot-registration
type: policy
scope: global
description: Policy for Telegram command registration in multi-computer setups.
---

## Rule

- Only one bot (the master) registers Telegram commands in a multi-computer supergroup.
- Configure `telegram.is_master: true` on the master and `false` on all others.
- BotCommand names include trailing spaces to avoid `@botname` binding.
- Non-master bots still implement the same command handlers.

## Rationale

- Prevents duplicate command listings and confusing UX in Telegram.

## Scope

- Applies to all Telegram adapters in multi-computer deployments.

## Enforcement or checks

- Verify `telegram.is_master` configuration per host.
- Confirm BotCommand definitions include trailing spaces on the master.

## Exceptions or edge cases

- None; multiple registrars are treated as misconfiguration.
