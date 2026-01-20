---
id: teleclaude/guide/multi-computer-setup
type: guide
scope: project
description: Steps and guardrails for running TeleClaude across multiple computers in one Telegram supergroup.
requires:
  - ../policy/telegram-command-registration.md
---

Guide
- Install TeleClaude on each computer with a unique bot token and computer name.
- Add all bots to the same Telegram supergroup and grant Manage Topics permissions.
- Configure each bot with the same supergroup ID and a shared trusted_bots list.
- Set telegram.is_master true on exactly one computer to register commands.
- Optionally enable Redis for AI-to-AI collaboration via MCP tools.
