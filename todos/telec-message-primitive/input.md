# telec-message-primitive — Input

telec message — person-addressed messaging primitive

## Vision

Agents need to send messages to people without knowing or caring which channel they're on. telec message is the person-addressed primitive: resolve the person from config, pick their preferred channel (or an explicit --channel override), and dispatch through the existing adapter infrastructure.

## Surface

telec message <person> <text>
telec message <person> --file <path> [--caption <text>]
telec message <person> --channel telegram|discord|whatsapp

Without --channel, resolves to the person's preferred_channel from their config record. The person record (telec config people) already exists — extend it with preferred_channel and per-channel identifiers (Telegram username, Discord user ID, WhatsApp number).

## Resolution flow

1. Resolve person name to config record (fuzzy match on name, exact on email)
2. Determine channel: explicit --channel flag > person's preferred_channel > system default
3. Resolve channel identifier from person's channels map
4. Dispatch through existing adapter: send_telegram.py pattern for Telegram, equivalent for Discord/WhatsApp

## Why now

- Agents doing proactive work need to reach humans without being in an active session
- Current workaround (telec sessions result) only works within the current session's origin adapter
- send_telegram.py proves the Telegram path works — this generalizes it
- Person config already exists, just needs channel identifiers added

## Config schema extension

people channels map: telegram username, discord user_id, whatsapp phone, plus preferred_channel field

## Key files

- teleclaude/entrypoints/send_telegram.py — existing direct Telegram send (reference)
- teleclaude/config/schema.py — person config schema (extend)
- teleclaude/cli/telec/surface.py — CLI surface (add message subcommand)
- teleclaude/adapters/telegram/message_ops.py — existing adapter send
- teleclaude/adapters/discord/message_ops.py — existing adapter send
