---
description: Steps to add a new Telegram command end-to-end.
id: teleclaude/procedure/add-telegram-command
scope: project
type: procedure
---

# Add Telegram Command — Procedure

## Goal

- @docs/policy/telegram-command-registration

- Add a new Telegram command end-to-end and wire it to CommandService.

- Command handler and command types are defined for the feature.

1. Register a `CommandHandler` in `teleclaude/adapters/telegram_adapter.py` `start()`.
2. Add a `BotCommand` with trailing space to the command list in `start()`.
3. Implement the handler using `_get_session_from_topic` as needed.
4. Map input to a typed command object in `teleclaude/types/commands.py`.
5. Dispatch via `CommandService` using `_dispatch_command` (pre/post hooks + broadcast).
6. Add the command to `UiCommands` in `teleclaude/core/events.py`.

- Command appears in Telegram UI and executes through CommandService.

- If the command does not show up, verify `telegram.is_master` and trailing space registration.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
