# Discord Bot API - Help Desk Integration

## Purpose

Integrate Discord as a customer-facing messaging channel. Leverages Forum Channels to mirror the Telegram "Control Room" architecture.

## Core Concepts

- **Forum Channels (Type 15)**: Multi-threaded channels where each customer session is a "Thread."
- **Webhooks**: Preferred for mirroring messages to make them appear as if they came from the original sender.
- **Message Content Intent**: REQUIRED for the bot to read customer inputs.
- **Snowflake**: The 64-bit unique identifier used for Users, Channels, and Messages.

## API Usage

### Creating a Forum Thread (Session Start)

```bash
POST /channels/<FORUM_CHANNEL_ID>/threads
{
  "name": "Session: <CUSTOMER_NAME>",
  "message": { "content": "Initializing Help Desk session..." }
}
```

## Constraints

- **Self-Bots**: Strictly forbidden; must use official Bot tokens.
- **Rate Limits**: Heavy on message sending; use webhooks for bursts.
- **Gateway**: Requires persistent WebSocket connection or a reliable Gateway Proxy.

## Gaps/Unknowns

- Interaction with Discord "Apps" (v2026) vs traditional Bot users.
- Persistent session storage for Snowflake mappings.

## Sources

- [Discord Developer Portal](https://discord.com/developers/docs)
