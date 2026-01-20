---
id: teleclaude/procedure/add-telegram-command
type: procedure
scope: project
description: Steps to add a new Telegram command end-to-end.
requires:
  - ../policy/telegram-command-registration.md
---

Steps
1) Register a CommandHandler in teleclaude/adapters/telegram_adapter.py start().
2) Add BotCommand with trailing space to the command list in start().
3) Implement the handler method using _get_session_from_topic.
4) Route the command in teleclaude/daemon.py handle_command.
5) Implement the daemon handler logic.
6) Add the command to UiCommands in teleclaude/core/events.py.

Outputs
- Command appears in Telegram UI and executes through the daemon pipeline.
