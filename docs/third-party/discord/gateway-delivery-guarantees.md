# Discord Gateway — Delivery Guarantees and Recovery

## Purpose

Document Discord Gateway delivery semantics and recovery mechanisms for building reliable message processing pipelines.

## Gateway Delivery Model

The Discord Gateway provides **at-most-once delivery** under normal operation:

- Events arrive via WebSocket as dispatch events (opcode 0), each with a sequence number `s`.
- There is **no explicit message acknowledgment**. The only ACK mechanism is Heartbeat ACK (opcode 11), which acknowledges heartbeats, not individual events.
- If an event handler fails, Discord does not know and will not redeliver.
- The reliability burden is entirely on the consumer.

## RESUME Mechanism

On disconnect, the bot can replay missed events via RESUME (opcode 6):

1. On initial connect, bot receives `READY` with `session_id` and `resume_gateway_url`.
2. Every dispatch event carries a sequence number `s`.
3. On disconnect, bot reconnects to `resume_gateway_url` and sends RESUME with `{token, session_id, seq}`.
4. Discord replays all events since `seq` in order, ending with a `RESUMED` event.
5. **Session window is ~90 seconds** (empirically observed, not officially documented). After expiry, Discord sends opcode 9 (Invalid Session, `d=false`) and the bot must re-IDENTIFY, losing all events in the gap.

`discord.py` handles RESUME automatically and transparently via its `DiscordWebSocket` class.

## REST API Message Backfill

`GET /channels/{channel_id}/messages` can recover messages missed outside the RESUME window:

- Supports `after` parameter with a message/snowflake ID to fetch newer messages.
- Returns up to 100 messages per request (default 50).
- `before`, `after`, `around` parameters are mutually exclusive.
- Rate limits: global 50 req/s, per-route limits are dynamic (check response headers).

Snowflake IDs encode timestamps (ms since Discord epoch 2015-01-01):

```python
DISCORD_EPOCH = 1420070400000  # milliseconds
def timestamp_to_snowflake(timestamp_ms: int) -> int:
    return (timestamp_ms - DISCORD_EPOCH) << 22
```

`discord.py`'s `channel.history(after=..., limit=100, oldest_first=True)` handles rate limiting internally.

## Interaction Acknowledgment (Slash Commands, Buttons)

Interactions offer a pseudo-transactional pattern:

- 3-second deadline to send initial response (including deferred responses).
- `DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE` (type 5) acknowledges receipt with loading indicator.
- Interaction token valid for 15 minutes for followup messages.
- Not applicable to regular text messages in forum threads.

## Reliable Processing Patterns

Since Discord provides no consumer-side ACK, production bots use:

1. **Write-Ahead Log**: Record message ID and payload to durable storage before processing. Background worker retries unprocessed entries.
2. **Idempotent Processing**: Track processed message IDs (UNIQUE constraint) to handle RESUME replays and REST backfill overlap.
3. **High-Water Mark**: Track highest processed message ID per channel. On startup, use `GET /channels/{id}/messages?after={hwm}` to backfill gaps.

## Sources

- [Discord Developer Portal — Gateway](https://discord.com/developers/docs/events/gateway)
- [Discord Developer Portal — Receiving and Responding to Interactions](https://discord.com/developers/docs/interactions/receiving-and-responding)
- [Discord Developer Portal — Get Channel Messages](https://discord.com/developers/docs/resources/channel#get-channel-messages)
- [discord.py Documentation](https://discordpy.readthedocs.io/en/stable/)
