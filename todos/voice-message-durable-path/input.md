# Input: voice-message-durable-path

## Problem

Failed voice transcriptions are silently dropped. If Whisper transcription returns None or fails, the message is lost entirely. This breaks the guaranteed delivery guarantee for voice messages.

This is a deferred enhancement from the guaranteed-inbound-delivery build phase.

## Scope

Implement durable retry path for voice messages in the inbound queue:

1. When voice transcription fails inline, enqueue the message with `message_type='voice'` and `payload_json` containing the source file reference (Discord CDN URL or Telegram `file_id`).
2. Extend `deliver_inbound()` to handle `message_type='voice'` rows: re-download from source, attempt transcription, send text result.
3. On transcription retry failure, mark failed and backoff exponentially.
4. Handle Discord CDN URL expiry: CDN URLs expire after ~24 hours. Store both CDN URL and local file path in `payload_json` as fallback.

## Deliverables

1. Update Discord `_handle_voice_attachment()` to enqueue voice on transcription failure instead of dropping.
2. Update Telegram voice handler similarly.
3. Extend `deliver_inbound()` to dispatch on `message_type` and handle voice retry path.
4. Add CDN/file_id recovery logic with expiry fallback.
5. Tests: verify voice messages retry on transcription failure; verify text result is sent after retry; verify CDN expiry handling.

## Definition of Done

- Voice messages with failed transcription are queued and retried, not dropped.
- Failed voice messages after max retries are marked 'failed' (not expired).
- Transcription retry is idempotent (same audio = same text).
- Tests pass; integration tested with Discord and Telegram voice messages.
