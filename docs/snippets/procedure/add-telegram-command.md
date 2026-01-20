---
description: Steps to add a new Telegram command end-to-end.
id: teleclaude/procedure/add-telegram-command
requires:
- teleclaude/policy/telegram-command-registration
scope: project
type: procedure
---

Steps
1) Register a CommandHandler in teleclaude/adapters/telegram_adapter.py start().
2) Add BotCommand with trailing space to the command list in start().
3) Implement the handler method using _get_session_from_topic.
4) Map input to a typed command object (teleclaude/types/commands.py).
5) Dispatch via CommandService using _dispatch_command (pre/post hooks + broadcast).
6) Add the command to UiCommands in teleclaude/core/events.py.

Outputs
- Command appears in Telegram UI and executes through CommandService.