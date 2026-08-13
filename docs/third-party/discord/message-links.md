---
description: Discord message links (jump URLs) — canonical URL forms for guild channels, threads, DMs, and specific messages
---

# Discord Message Links (Jump URLs)

## Purpose

Reference for constructing native Discord jump URLs — the clickable links that open a channel, thread, DM, or specific message in the Discord client (in-app and in-browser). Plain HTTPS; no custom protocol required.

## URL forms

| Target                    | Form                                                                |
| ------------------------- | ------------------------------------------------------------------- |
| Guild channel             | `https://discord.com/channels/<guild_id>/<channel_id>`              |
| Guild thread              | `https://discord.com/channels/<guild_id>/<thread_id>`               |
| Specific message in guild | `https://discord.com/channels/<guild_id>/<channel_id>/<message_id>` |
| DM channel                | `https://discord.com/channels/@me/<channel_id>`                     |
| Specific message in DM    | `https://discord.com/channels/@me/<channel_id>/<message_id>`        |

## Semantics

- All ids are 64-bit snowflakes rendered as decimal strings.
- A thread id occupies the channel position — threads are channels in Discord's model; no separate thread segment exists.
- The trailing `<message_id>` segment is optional: without it the link opens the channel or thread; with it the client scrolls to the message.
- The literal `@me` replaces the guild id for DM and group-DM channels. Such a link resolves only for a viewer who participates in that DM.
- The client resolves a link only for viewers with access to the target guild/channel; the URL itself carries no authorization.

## Reference implementation

discord.py (the library TeleClaude's Discord adapter uses) constructs exactly these forms in its `jump_url` properties:

- `discord/message.py` — `MessageReference.jump_url`: `https://discord.com/channels/{guild_id or '@me'}/{channel_id}/{message_id}`
- `discord/threads.py` — `Thread.jump_url`: `https://discord.com/channels/{guild.id}/{thread.id}`
- `discord/channel.py` — `DMChannel.jump_url`: `https://discord.com/channels/@me/{id}`; `PartialMessageable.jump_url`: guild form when `guild_id` set, `@me` form otherwise

## Sources

- https://github.com/Rapptz/discord.py/blob/master/discord/message.py (jump_url construction; verified against the installed package in this repo)
- https://support.discord.com/hc/en-us/articles/360045138571 (Beginner's Guide to Message Links)
- https://docs.discord.com/developers/resources/message (message resource; ids as snowflakes)
