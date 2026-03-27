# Task 6b: Convert MessageMetadata per-message `channel_metadata` to typed metadata

## Context

Part of the `identity-origin-cleanup` work. Session-level origin metadata has been converted to `origin_metadata`. Per-message context (telegram message_id, discord actor fields) still uses deprecated `MessageMetadata.channel_metadata` dict.

## Scope

- Telegram: message_id extraction
- Discord: actor fields (user_id, etc.)
- WhatsApp: any per-message metadata
- Define new typed fields on MessageMetadata
- Update adapters to populate typed fields instead of dict

## Success Criteria

- MessageMetadata has typed fields for all per-message context currently in channel_metadata dicts
- All edge adapters use typed fields instead of dict
- Tests verify typed field population
- No regressions in message routing
