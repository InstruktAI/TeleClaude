# help-desk-discord — Implementation Plan

## Approach

Implement the `DiscordAdapter` by subclassing `UiAdapter`. We will use `discord.py` to manage the gateway connection and event loop. The adapter will be responsible for translating Discord `Message` events into TeleClaude `process_message` calls.

## Proposed Changes

### 1. Adapter Implementation

- **File**: `teleclaude/adapters/discord_adapter.py`
- **Class**: `DiscordAdapter(UiAdapter)`
- **Key Methods**:
  - `start()`: Initialize `discord.Client` and run in background task.
  - `stop()`: Close the client connection.
  - `create_channel()`: Create a new Forum Thread for the session.
  - `send_message()`: Post to the specific thread.
  - `_handle_on_message()`: Webhook/Event listener that routes to `client.process_message`.

### 2. Configuration

- **File**: `teleclaude/config/models.py`
- **Change**: Add `DiscordConfig` (token, guild_id, help_desk_channel_id).
- **File**: `teleclaude.sample.yml`
- **Change**: Add discord section.

### 3. Identity & Routing

- Use `PersonEntry` logic to bind Discord Snowflake -> Internal Identity.
- Force `help-desk` project routing for all incoming Discord messages.

## Task Sequence

1. [x] Scaffold `discord_adapter.py` with `discord.py` skeleton.
2. [ ] Implement gateway event handlers (`on_ready`, `on_message`).
3. [ ] Implement `create_channel` using Discord Forum Threads (Type 15).
4. [ ] Wire `DiscordAdapter` into `AdapterClient.start()`.
5. [ ] Verify ingress/egress with a local mock Discord bot.

## Risks & Unknowns

- Discord rate limits on rapid message editing (UiAdapter pattern).
- Ensuring the Discord loop doesn't block the main TeleClaude event loop (should run in `AdapterClient`'s task registry).
