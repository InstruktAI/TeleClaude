---
description: Only the master bot registers Telegram commands, and command names include
  trailing spaces.
id: teleclaude/policy/telegram-command-registration
requires:
- teleclaude/architecture/telegram-adapter
scope: project
type: policy
---

Policy
- Exactly one bot registers commands in a multi-bot supergroup; set telegram.is_master true on the master only.
- Non-master bots must not publish command lists.
- BotCommand definitions include trailing spaces to avoid /command@botname binding.