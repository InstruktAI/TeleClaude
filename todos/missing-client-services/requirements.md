# Requirements: missing-client-services

## Goal

Create Discord and WhatsApp low-level service modules (`teleclaude/services/discord.py`
and `teleclaude/services/whatsapp.py`) and their corresponding event delivery adapters
(`teleclaude_events/delivery/discord.py` and `teleclaude_events/delivery/whatsapp.py`),
then wire them into the daemon's event processing pipeline alongside the existing
Telegram delivery adapter.

The existing pattern: `teleclaude/services/telegram.py` provides `send_telegram_dm()`,
which is wrapped by `TelegramDeliveryAdapter` in `teleclaude_events/delivery/telegram.py`,
and registered in `daemon.py` for admin push notifications. Discord and WhatsApp need
the same two-layer treatment.

## Scope

### In scope:

- `teleclaude/services/discord.py` — standalone `send_discord_dm(user_id, content)` using
  Discord REST API (`POST /users/@me/channels` + `POST /channels/{id}/messages`). Uses
  `DISCORD_BOT_TOKEN` env var. httpx-based, matching the telegram.py pattern.
- `teleclaude/services/whatsapp.py` — standalone `send_whatsapp_message(phone_number, content)`
  using WhatsApp Cloud API (`POST graph.facebook.com/{api_version}/{phone_number_id}/messages`).
  Config params (phone_number_id, access_token, api_version) passed as arguments, matching
  how WhatsAppAdapter already calls the same API.
- `teleclaude_events/delivery/discord.py` — `DiscordDeliveryAdapter` following the exact
  same pattern as `TelegramDeliveryAdapter`: accepts a `send_fn` callable, level threshold,
  and the user's Discord user ID.
- `teleclaude_events/delivery/whatsapp.py` — `WhatsAppDeliveryAdapter` following the same
  pattern, with the phone number as the destination identifier.
- Update `teleclaude_events/delivery/__init__.py` to export both new adapters.
- Wire both adapters into `daemon.py`'s `_start_event_processing` method, iterating admin
  people configs for `creds.discord.user_id` and `creds.whatsapp.phone_number`.
- Unit tests for all four new modules (two services, two delivery adapters).

### Out of scope:

- Changes to the Discord UI adapter (`teleclaude/adapters/discord_adapter.py`) — that is
  the interactive session management layer, not the notification delivery layer.
- Changes to the WhatsApp UI adapter (`teleclaude/adapters/whatsapp_adapter.py`).
- File/document attachment support in the new services (text-only for initial delivery).
- Changes to the person config schema — `DiscordCreds` and `WhatsAppCreds` already exist
  in `teleclaude/config/schema.py`.

## Success Criteria

- [ ] `send_discord_dm(user_id="123", content="test")` sends a Discord DM via REST API
- [ ] `send_whatsapp_message(phone_number="+1234", content="test", phone_number_id="...", access_token="...", api_version="v21.0")` sends a WhatsApp text message via Cloud API
- [ ] `DiscordDeliveryAdapter.on_notification()` filters by level and delegates to `send_discord_dm`
- [ ] `WhatsAppDeliveryAdapter.on_notification()` filters by level and delegates to `send_whatsapp_message`
- [ ] Daemon registers Discord delivery adapters for admins with `creds.discord.user_id`
- [ ] Daemon registers WhatsApp delivery adapters for admins with `creds.whatsapp.phone_number`
- [ ] All new modules have unit tests covering success, error, and threshold/filtering paths
- [ ] `make test` passes
- [ ] `make lint` passes

## Constraints

- Service modules must use httpx (not the discord.py library or other SDKs) to match existing patterns.
- Service modules must NOT import from adapters or core — they are standalone helpers.
- Delivery adapters must follow the exact `on_notification` callback signature used by
  the event pipeline's push callback interface.
- WhatsApp service must accept API config as parameters (not read from global config
  directly), matching the `send_telegram_dm` pattern where the token is read from env.

## Risks

- Discord REST API for creating DM channels requires the bot to share a guild with the
  target user. This is an inherent Discord limitation, not something the code can work
  around. Document this in the service module docstring.
- WhatsApp Cloud API has a 24-hour messaging window for non-template messages. The
  service function sends text messages (not templates). If the window has closed, the
  API returns an error. The delivery adapter handles this gracefully (log and continue).
