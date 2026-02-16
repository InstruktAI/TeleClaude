# Discord Media Handling — Input

## Problem

The Discord adapter silently drops voice messages, image uploads, and file attachments. In `_handle_on_message`, only `message.content` (text) is processed — if a message has no text (common for voice-only or image-only messages), it returns early. Even when text accompanies an attachment, the attachment itself is ignored.

This makes the Discord help desk experience incomplete for customers who send voice notes or screenshots.

## Source

Discovered during post-delivery testing of `help-desk-discord` (2026-02-16). The Telegram adapter handles all three media types; the Discord adapter has zero equivalent handling.

## What's missing

### Voice messages

- Discord voice messages arrive as attachments with OGG/WebM content type
- Telegram equivalent: `_handle_voice_message()` in `teleclaude/adapters/telegram/input_handlers.py`
  - Downloads the OGG file to temp location
  - Routes through `handle_voice` command (which transcribes via Whisper)
  - Deduplication via `_processed_voice_messages` set
- Discord needs: detect voice attachment, download, route through same `handle_voice` command

### Image uploads

- Discord images arrive as attachments with image content types (or as embeds)
- Telegram equivalent: `_handle_file_attachment()` handles `message.photo` (picks largest PhotoSize)
  - Saves to `{session_workspace}/photos/photo_{message_id}.jpg`
  - Injects file path context into the AI session
- Discord needs: detect image attachments, download, save to session workspace, inject into session

### File attachments

- Discord files arrive as attachments with arbitrary content types
- Telegram equivalent: `_handle_file_attachment()` handles `message.document`
  - Saves to `{session_workspace}/files/{filename}`
  - Injects file path context into the AI session
- Discord needs: same pattern — download, save, inject

## Key code references

- **Silent drop:** `discord_adapter.py` `_handle_on_message` lines 347-349 — checks `content` only
- **Telegram voice:** `telegram/input_handlers.py` `_handle_voice_message()` (line ~239)
- **Telegram files:** `telegram/input_handlers.py` `_handle_file_attachment()` (line ~330)
- **Voice command:** `HandleVoiceCommand` in command service
- **Session workspace:** `get_session_output_dir(session.session_id)`
