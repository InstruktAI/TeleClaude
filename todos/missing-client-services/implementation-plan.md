# Implementation Plan: missing-client-services

## Overview

Follow the existing two-layer pattern (service + delivery adapter) established by
`teleclaude/services/telegram.py` and `teleclaude_events/delivery/telegram.py`.
Create four new modules, update one export file, add wiring in daemon.py, and write
tests for everything.

## Phase 1: Service Modules

### Task 1.1: Create `teleclaude/services/discord.py`

**File(s):** `teleclaude/services/discord.py`

- [ ] Create `send_discord_dm(user_id: str, content: str, *, token_env: str = "DISCORD_BOT_TOKEN", timeout_s: float = 10.0) -> str`
- [ ] Step 1: Read bot token from `os.getenv(token_env)`, raise `ValueError` if missing
- [ ] Step 2: Validate content is not empty, raise `ValueError` if so
- [ ] Step 3: Create DM channel via `POST https://discord.com/api/v10/users/@me/channels` with `{"recipient_id": user_id}` and `Authorization: Bot {token}` header
- [ ] Step 4: Extract `channel_id` from response
- [ ] Step 5: Send message via `POST https://discord.com/api/v10/channels/{channel_id}/messages` with `{"content": content[:2000]}` (Discord's 2000-char limit)
- [ ] Step 6: Log warning if content was truncated
- [ ] Step 7: Return message ID as string
- [ ] Step 8: Handle HTTP errors (status >= 400) with clear `RuntimeError` messages, matching telegram.py's error handling pattern

### Task 1.2: Create `teleclaude/services/whatsapp.py`

**File(s):** `teleclaude/services/whatsapp.py`

- [ ] Create `send_whatsapp_message(phone_number: str, content: str, *, phone_number_id: str, access_token: str, api_version: str = "v21.0", timeout_s: float = 10.0) -> str`
- [ ] Step 1: Validate phone_number, content, phone_number_id, access_token are non-empty
- [ ] Step 2: Build URL: `https://graph.facebook.com/{api_version}/{phone_number_id}/messages`
- [ ] Step 3: Build payload: `{"messaging_product": "whatsapp", "to": phone_number, "type": "text", "text": {"body": content[:4096]}}` (WhatsApp's limit)
- [ ] Step 4: POST with `Authorization: Bearer {access_token}` header
- [ ] Step 5: Extract `messages[0].id` from response
- [ ] Step 6: Log warning if content was truncated
- [ ] Step 7: Return message ID as string
- [ ] Step 8: Handle HTTP errors with clear `RuntimeError` messages

## Phase 2: Delivery Adapters

### Task 2.1: Create `teleclaude_events/delivery/discord.py`

**File(s):** `teleclaude_events/delivery/discord.py`

- [ ] Create `DiscordDeliveryAdapter` class following `TelegramDeliveryAdapter` pattern exactly
- [ ] Constructor: `__init__(self, user_id: str, send_fn: Callable[..., Coroutine], min_level: int = int(EventLevel.WORKFLOW))`
- [ ] Method: `on_notification(self, notification_id, event_type, level, was_created, is_meaningful)` — same signature as Telegram adapter
- [ ] Filter: skip if `not was_created` or `level < self._min_level`
- [ ] Format message: `f"[{event_type}] Notification #{notification_id} created."`
- [ ] Call `send_fn(user_id=self._user_id, content=message)`
- [ ] Catch all exceptions, log and continue (never crash the pipeline)

### Task 2.2: Create `teleclaude_events/delivery/whatsapp.py`

**File(s):** `teleclaude_events/delivery/whatsapp.py`

- [ ] Create `WhatsAppDeliveryAdapter` class following same pattern
- [ ] Constructor: `__init__(self, phone_number: str, send_fn: Callable[..., Coroutine], min_level: int = int(EventLevel.WORKFLOW))`
- [ ] Same `on_notification` filtering and message formatting
- [ ] Call `send_fn(phone_number=self._phone_number, content=message)`
- [ ] Same exception handling

### Task 2.3: Update `teleclaude_events/delivery/__init__.py`

**File(s):** `teleclaude_events/delivery/__init__.py`

- [ ] Add imports for `DiscordDeliveryAdapter` and `WhatsAppDeliveryAdapter`
- [ ] Update `__all__` to include both

## Phase 3: Daemon Wiring

### Task 3.1: Register Discord and WhatsApp delivery adapters in daemon.py

**File(s):** `teleclaude/daemon.py`

- [ ] After the existing Telegram delivery adapter registration block (lines 1693-1718), add a Discord block:
  - Gate: `if config.discord.enabled:` (DiscordConfig always exists; `.enabled` is the feature toggle)
  - Import `send_discord_dm` from `teleclaude.services.discord`
  - Import `DiscordDeliveryAdapter` from `teleclaude_events.delivery.discord`
  - Iterate admin people, load person config, check `person_cfg.creds.discord.user_id`
  - If user_id exists, create `DiscordDeliveryAdapter(user_id=user_id, send_fn=send_discord_dm)` and append to `push_callbacks`
- [ ] Add a WhatsApp block:
  - Gate: `if config.whatsapp.enabled:` (WhatsAppConfig always exists; `.enabled` derives from config + env vars)
  - Import `send_whatsapp_message` from `teleclaude.services.whatsapp`
  - Import `WhatsAppDeliveryAdapter` from `teleclaude_events.delivery.whatsapp`
  - Iterate admin people, load person config, check `person_cfg.creds.whatsapp.phone_number`
  - Bind WhatsApp API params from global config: `phone_number_id=config.whatsapp.phone_number_id`, `access_token=config.whatsapp.access_token`, `api_version=config.whatsapp.api_version`
  - Create a partial/lambda wrapping `send_whatsapp_message` with bound API params so the adapter only needs `phone_number` and `content`
  - Create `WhatsAppDeliveryAdapter(phone_number=phone_number, send_fn=bound_send_fn)` and append to `push_callbacks`

## Phase 4: Validation

### Task 4.1: Unit tests for services

**File(s):** `tests/unit/test_discord_service.py`, `tests/unit/test_whatsapp_service.py`

- [ ] Discord service tests (matching `test_telegram.py` pattern):
  - `test_send_dm_success` — mock httpx, verify two API calls (create DM, send message)
  - `test_missing_token_raises`
  - `test_empty_content_raises`
  - `test_api_error_raises` — HTTP >= 400
  - `test_truncation_warning` — content > 2000 chars
- [ ] WhatsApp service tests:
  - `test_send_message_success` — mock httpx, verify POST to Cloud API
  - `test_missing_access_token_raises`
  - `test_empty_content_raises`
  - `test_api_error_raises`
  - `test_truncation_warning` — content > 4096 chars

### Task 4.2: Unit tests for delivery adapters

**File(s):** `tests/unit/test_teleclaude_events/test_discord_adapter.py`, `tests/unit/test_teleclaude_events/test_whatsapp_adapter.py`

- [ ] Discord delivery adapter tests (matching `test_telegram_adapter.py` exactly):
  - `test_sends_when_created_and_level_meets_threshold`
  - `test_skips_when_not_created`
  - `test_skips_when_level_below_min`
  - `test_sends_when_level_above_min`
  - `test_handles_send_exception_gracefully`
- [ ] WhatsApp delivery adapter tests — same five test cases

### Task 4.3: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
