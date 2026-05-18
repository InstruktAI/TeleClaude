---
description: 'Policy for Telegram command registration in multi-computer setups.'
id: 'project/policy/master-bot-registration'
scope: 'project'
type: 'policy'
visibility: 'public'
---

# Master Bot Registration — Policy

## Rules

- Only one bot (the master) registers Telegram commands in a multi-computer supergroup.
- Configure `telegram.is_master: true` on the master and `false` on all others.
- BotCommand names include trailing spaces to avoid `@botname` binding.
- Non-master bots still implement the same command handlers.
- Do not register commands from background/worker bots.

## Rationale

- Prevents duplicate command listings and confusing UX in Telegram.

## Scope

- Applies to all Telegram adapters in multi-computer deployments.

## Enforcement

- Verify `telegram.is_master` configuration per host.
- Confirm BotCommand definitions include trailing spaces on the master.

## Exceptions

- None; multiple registrars are treated as misconfiguration.
