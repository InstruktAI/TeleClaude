---
id: teleclaude/policy/telegram-command-registration
type: policy
scope: project
description: Only the master bot registers Telegram commands, and command names include trailing spaces.
requires:
  - ../architecture/telegram-adapter.md
---

Policy
- Exactly one bot (the master) registers Telegram commands in a multi-bot supergroup.
- BotCommand definitions include trailing spaces to avoid /command@botname binding.
- Non-master bots must not publish command lists.
