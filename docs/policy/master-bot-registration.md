---
id: policy/master-bot-registration
type: policy
scope: global
description: Policy for Telegram command registration in multi-computer setups.
---

# Master Bot Registration — Policy

## Rule

- Only one bot (the master) registers Telegram commands in a multi-computer supergroup.
- Configure `telegram.is_master: true` on the master and `false` on all others.
- BotCommand names include trailing spaces to avoid `@botname` binding.
- Non-master bots still implement the same command handlers.

- Prevents duplicate command listings and confusing UX in Telegram.

- Applies to all Telegram adapters in multi-computer deployments.

- Verify `telegram.is_master` configuration per host.
- Confirm BotCommand definitions include trailing spaces on the master.

- None; multiple registrars are treated as misconfiguration.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
