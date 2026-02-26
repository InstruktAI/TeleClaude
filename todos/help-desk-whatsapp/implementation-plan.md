# Implementation Plan: help-desk-whatsapp

## Overview

Build a WhatsApp Business Cloud API adapter following the established UiAdapter pattern (Telegram/Discord). The adapter handles bidirectional messaging: outbound via WhatsApp Cloud API HTTP calls, inbound via webhook events routed through the hook service. Uses `httpx` for all API communication. Customer sessions follow the help desk platform patterns already delivered.

## Phase 1: Data Model & Configuration

### Task 1.1: WhatsApp adapter metadata

**File(s):** `teleclaude/core/models.py`

- [x] Add `WhatsAppAdapterMetadata` dataclass with fields:
  - `phone_number: Optional[str]` — customer phone number (E.164)
  - `conversation_id: Optional[str]` — WhatsApp conversation ID
  - `output_message_id: Optional[str]` — last sent message ID for edit tracking
  - `badge_sent: bool = False` — session badge sent flag
  - `char_offset: int = 0` — pagination state for threaded output
  - `last_customer_message_at: Optional[str]` — ISO 8601 timestamp for 24h window tracking
- [x] Add `_whatsapp: Optional[WhatsAppAdapterMetadata]` field to `UiAdapterMetadata`
- [x] Add `get_whatsapp()` method to `UiAdapterMetadata` (lazy init, same as `get_telegram()`)
- [x] Update `SessionAdapterMetadata.__init__()` to accept `whatsapp` shorthand arg
- [x] Verify serialization/deserialization roundtrip with existing DB layer

### Task 1.2: WhatsApp config schema

**File(s):** `teleclaude/config/schema.py`, `teleclaude/config/defaults.py` (or equivalent)

- [x] Add `WhatsAppConfig` dataclass:
  - `enabled: bool = False`
  - `phone_number_id: Optional[str]` — from `$WHATSAPP_PHONE_NUMBER_ID`
  - `access_token: Optional[str]` — from `$WHATSAPP_ACCESS_TOKEN`
  - `webhook_secret: Optional[str]` — from `$WHATSAPP_WEBHOOK_SECRET`
  - `verify_token: Optional[str]` — from `$WHATSAPP_VERIFY_TOKEN`
  - `api_version: str = "v21.0"` — pinned API version (v20.0 expired May 2025)
  - `template_name: Optional[str]` — pre-approved template for out-of-window messages
  - `template_language: str = "en_US"` — template language code
- [x] Integrate `WhatsAppConfig` into root config schema
- [x] Add activation rule: enabled when `phone_number_id` and `access_token` are present

### Task 1.3: Identity resolution for WhatsApp

**File(s):** `teleclaude/core/identity.py` (or equivalent identity resolution module)

- [x] Add WhatsApp identity key format: `whatsapp:{phone_number}` (E.164, no `+` prefix)
- [x] Add person config credential path: `creds.whatsapp.phone_number`
- [x] Implement phone number normalization: strip non-numeric except leading `+`, convert to E.164
- [x] Unknown numbers resolve to `customer` role (existing default behavior)

---

## Phase 2: Adapter Core (Outbound)

### Task 2.1: WhatsApp adapter class scaffold

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [x] Create `WhatsAppAdapter(UiAdapter)` class
- [x] Set `ADAPTER_KEY = "whatsapp"`
- [x] Initialize with `httpx.AsyncClient` for WhatsApp Cloud API calls
- [x] Store config refs: `phone_number_id`, `access_token`, `api_version`
- [x] Implement `start()`: validate credentials, verify API connectivity (optional: send test API call)
- [x] Implement `stop()`: close httpx client, cleanup

### Task 2.2: Channel management

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [x] `create_channel()` — Store customer phone number in WhatsApp adapter metadata; no platform-side channel creation (WhatsApp conversations are implicit)
- [x] `update_channel_title()` — No-op, return True (WhatsApp has no channel concept)
- [x] `close_channel()` — Mark session as closed in metadata, return True
- [x] `reopen_channel()` — Clear closed flag, return True
- [x] `delete_channel()` — No-op, return True
- [x] `ensure_channel()` — Ensure phone number is stored in metadata; skip non-customer sessions

### Task 2.3: Outbound messaging

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [x] `send_message()` — POST text message to `https://graph.facebook.com/{api_version}/{phone_number_id}/messages`
  - Payload: `{"messaging_product": "whatsapp", "to": "{recipient}", "type": "text", "text": {"body": "..."}}`
  - Handle message splitting for texts > 4096 chars
  - Track 24h window: if outside window, use template message
  - Return WhatsApp message ID (`wamid`)
- [x] `edit_message()` — Return False (WhatsApp does not support message editing)
- [x] `delete_message()` — Return False (WhatsApp does not support message deletion)
- [x] `send_file()` — Upload media via POST `/{phone_number_id}/media`, then send media message referencing the `media_id`
  - Support images (image/jpeg, image/png), documents, audio
  - Caption limited to 1024 chars
- [x] `get_max_message_length()` — Return 4096

### Task 2.4: Typing indicator and read receipts

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [x] `send_typing_indicator()` — POST to messages endpoint with `{"messaging_product": "whatsapp", "status": "read", "message_id": "{last_received_message_id}"}`
- [x] Store last received message ID in adapter metadata for read receipt targeting
- [x] Fire-and-forget pattern: catch all exceptions, log at debug level

### Task 2.5: Platform-specific overrides

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [x] `_convert_markdown_for_platform()` — Convert markdown to WhatsApp format:
  - Bold: `**text**` → `*text*`
  - Italic: `*text*` or `_text_` → `_text_`
  - Strikethrough: `~~text~~` → `~text~`
  - Code: `` `text` `` → ` ```text``` `
  - Strip unsupported formatting (headings, links with display text, images)
- [x] `_fit_output_to_limit()` — Truncate output to 4096 chars with truncation indicator
- [x] `_build_output_metadata()` — Return empty dict (no inline keyboards on WhatsApp)
- [x] `format_output()` — Apply WhatsApp markdown conversion to tmux output

### Task 2.6: Adapter registration

**File(s):** `teleclaude/core/adapter_client.py`

- [x] Add WhatsApp adapter startup in `AdapterClient.start()`:
  - Check if WhatsApp config is enabled and credentials present
  - Instantiate `WhatsAppAdapter(self)`
  - Call `await whatsapp.start()`
  - Register in `self.adapters["whatsapp"]`
  - Log startup success
- [x] Import `WhatsAppAdapter` at module level

---

## Phase 3: Inbound Message Handling

### Task 3.1: WhatsApp normalizer

**File(s):** `teleclaude/hooks/normalizers/whatsapp.py` (new)

- [x] Implement `normalize_whatsapp_webhook(payload: dict, headers: dict) -> list[HookEvent]`:
  - Parse Meta's nested structure: `entry[].changes[].value`
  - Handle message types: `text`, `image`, `document`, `audio`, `voice`, `video`
  - Handle status updates: `sent`, `delivered`, `read` (ignore or log)
  - Extract sender phone number, message ID, timestamp
  - Return list of `HookEvent` (one per message in payload; Meta can batch)
  - Source: `"whatsapp"`, Type: `"message.text"`, `"message.image"`, `"message.voice"`, etc.
- [x] Register normalizer in `NormalizerRegistry` during daemon startup

### Task 3.2: Inbound message handler

**File(s):** `teleclaude/hooks/handlers/whatsapp.py` (new)

- [x] Implement `handle_whatsapp_event(event: HookEvent) -> None`:
  - Extract phone number from event properties
  - Resolve identity: `whatsapp:{phone_number}` → person lookup
  - Find existing session for this phone number or create new customer session
  - Route by message type:
    - Text → inject as user message into session
    - Image/document → download media, save to workspace, dispatch file command
    - Voice/audio → download media, dispatch voice command (Whisper transcription)
  - Update `last_customer_message_at` in adapter metadata (24h window tracking)
- [x] Media download helper: `GET /{media_id}` for URL, then download file with access token in Authorization header
- [x] Register as built-in global subscription handler

### Task 3.3: Webhook verification

**File(s):** `teleclaude/hooks/normalizers/whatsapp.py` or adapter

- [x] WhatsApp verification challenge is handled by `InboundEndpointRegistry` GET handler (already supports `hub.verify_token`)
- [x] Verify that existing GET handler matches WhatsApp's challenge format: `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`
- [x] HMAC-SHA256 signature verification for POST payloads via `X-Hub-Signature-256` header

---

## Phase 4: Validation

### Task 4.1: Unit tests

**File(s):** `tests/unit/test_whatsapp_adapter.py` (new)

- [x] Test outbound message sending (mock httpx)
- [x] Test message splitting for long texts
- [x] Test typing indicator / read receipt sending
- [x] Test markdown conversion for WhatsApp format
- [x] Test 24h window detection and template fallback
- [x] Test media upload and send
- [x] Test adapter metadata serialization roundtrip
- [x] Test config validation and activation rules
- [x] Test identity resolution with WhatsApp phone numbers

### Task 4.2: Integration tests

**File(s):** `tests/integration/test_whatsapp_flow.py` (new)

- [x] Test normalizer: raw Meta webhook payload → HookEvent list
- [x] Test handler: HookEvent → session creation → message injection (mocked adapter)
- [x] Test end-to-end: webhook → normalizer → handler → adapter response (all mocked external calls)
- [x] Test voice message flow: webhook → download → transcription → session

### Task 4.3: Quality checks

- [x] Run `make test` — all tests pass
- [x] Run `make lint` — no new violations
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm all requirements traced to implementation tasks
- [x] Confirm all implementation tasks marked `[x]`
- [x] Document any deferrals in `deferrals.md` (if applicable)
- [x] Confirm adapter metadata model is consistent with Telegram/Discord patterns
- [x] Confirm no hardcoded credentials or secrets in code
