---
id: teleclaude/faq/common-issues
type: faq
scope: project
description: Common operational questions and quick fixes.
requires: []
---

FAQ
Q: The daemon will not start or crashes immediately. What should I do?
A: Disable auto-restart temporarily, kill stale processes, run a short foreground test, then re-enable the service and run make status.

Q: Telegram commands do not respond.
A: Ensure the bot is admin in the supergroup, the user is whitelisted, and the bot token matches the .env configuration.

Q: Cross-computer MCP requests time out.
A: Check Redis connectivity, verify the target computer is online, and inspect recent logs for transport errors.
