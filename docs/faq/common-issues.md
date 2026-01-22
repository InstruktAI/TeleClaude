---
id: faq/common-issues
type: faq
scope: global
description: Frequently asked questions and common troubleshooting steps.
---

# Common Issues (FAQ)

## Q: Why isn't my bot responding in the supergroup?

- **A**: Ensure the bot is an **admin**. Non-admin bots cannot manage topics or read all messages in some group configurations.
- **A**: Verify your Telegram User ID is in the `TELEGRAM_USER_IDS` whitelist in `.env`.
- **A**: Confirm the daemon is healthy with `make status` and recent logs.

## Q: "Another daemon instance is already running" error?

- **A**: This usually means a stale `teleclaude.pid` file. If `make status` shows no running process, `rm teleclaude.pid` and try again.

## Q: Why do I see duplicate bot commands in the menu?

- **A**: More than one bot has `telegram.is_master: true`. Only one should be master.

## Q: Why are tool calls timing out?

- **A**: Check daemon health and MCP socket availability; restart if needed.

## Q: My tmux session died, is the session lost?

- **A**: TeleClaude will try to reconnect, but if the tmux process is gone, you must start a `/new-session`. Commands in progress are lost if tmux crashes.
