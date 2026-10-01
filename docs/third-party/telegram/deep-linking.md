---
description: Telegram bot deep links — the private-chat start link, how the bot receives its parameter, and the parameter's character set and length limit.
---

# Telegram Bot Deep Linking

## Purpose

Reference for the link that opens a private chat with a bot and hands the bot a
parameter on first contact. TeleClaude's Telegram adapter reads that parameter
from its private chats.

## Link forms

| Target                  | Form                                                 |
| ----------------------- | ---------------------------------------------------- |
| Private chat with a bot | `https://t.me/<bot_username>?start=<parameter>`      |
| Add the bot to a group  | `https://t.me/<bot_username>?startgroup=<parameter>` |

## Semantics

- Opening the private-chat link starts a chat with that bot, and the bot
  receives the message `/start <parameter>`.
- The group form prompts the user to pick a group; the bot receives
  `/start@<bot_username> <parameter>` there.
- Allowed characters in the parameter: `A-Z`, `a-z`, `0-9`, `_` and `-`.
- The parameter is at most 64 characters long.
- Telegram recommends base64url for binary or other content outside that set.
- The link names one bot, and the user who opens it talks to that bot.
- Bots can't start conversations with users: a user must add the bot to a
  group or send it a message first.

## Sources

- https://core.telegram.org/bots/features#deep-linking
- https://core.telegram.org/bots (how bots differ from users)
