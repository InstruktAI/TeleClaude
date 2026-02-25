# Implementation Plan: help-desk-whatsapp

## Overview

Build a WhatsApp Business Cloud API adapter following the established UiAdapter pattern (Telegram/Discord). The adapter handles bidirectional messaging: outbound via WhatsApp Cloud API HTTP calls, inbound via webhook events routed through the hook service. Uses `httpx` for all API communication. Customer sessions follow the help desk platform patterns already delivered.

## Phase 1: Data Model & Configuration

### Task 1.1: WhatsApp adapter metadata

**File(s):** `teleclaude/core/models.py`

- [ ] Add `WhatsAppAdapterMetadata` dataclass with fields:
  - `phone_number: Optional[str]` — customer phone number (E.164)
  - `conversation_id: Optional[str]` — WhatsApp conversation ID
  - `output_message_id: Optional[str]` — last sent message ID for edit tracking
  - `badge_sent: bool = False` — session badge sent flag
  - `char_offset: int = 0` — pagination state for threaded output
  - `last_customer_message_at: Optional[str]` — ISO 8601 timestamp for 24h window tracking
- [ ] Add `_whatsapp: Optional[WhatsAppAdapterMetadata]` field to `UiAdapterMetadata`
- [ ] Add `get_whatsapp()` method to `UiAdapterMetadata` (lazy init, same as `get_telegram()`)
- [ ] Update `SessionAdapterMetadata.__init__()` to accept `whatsapp` shorthand arg
- [ ] Verify serialization/deserialization roundtrip with existing DB layer

### Task 1.2: WhatsApp config schema

**File(s):** `teleclaude/config/schema.py`, `teleclaude/config/defaults.py` (or equivalent)

- [ ] Add `WhatsAppConfig` dataclass:
  - `enabled: bool = False`
  - `phone_number_id: Optional[str]` — from `$WHATSAPP_PHONE_NUMBER_ID`
  - `access_token: Optional[str]` — from `$WHATSAPP_ACCESS_TOKEN`
  - `webhook_secret: Optional[str]` — from `$WHATSAPP_WEBHOOK_SECRET`
  - `verify_token: Optional[str]` — from `$WHATSAPP_VERIFY_TOKEN`
  - `api_version: str = "v21.0"` — pinned API version (v20.0 expired May 2025)
  - `template_name: Optional[str]` — pre-approved template for out-of-window messages
  - `template_language: str = "en_US"` — template language code
- [ ] Integrate `WhatsAppConfig` into root config schema
- [ ] Add activation rule: enabled when `phone_number_id` and `access_token` are present

### Task 1.3: Identity resolution for WhatsApp

**File(s):** `teleclaude/core/identity.py` (or equivalent identity resolution module)

- [ ] Add WhatsApp identity key format: `whatsapp:{phone_number}` (E.164, no `+` prefix)
- [ ] Add person config credential path: `creds.whatsapp.phone_number`
- [ ] Implement phone number normalization: strip non-numeric except leading `+`, convert to E.164
- [ ] Unknown numbers resolve to `customer` role (existing default behavior)

---

## Phase 2: Adapter Core (Outbound)

### Task 2.1: WhatsApp adapter class scaffold

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [ ] Create `WhatsAppAdapter(UiAdapter)` class
- [ ] Set `ADAPTER_KEY = "whatsapp"`
- [ ] Initialize with `httpx.AsyncClient` for WhatsApp Cloud API calls
- [ ] Store config refs: `phone_number_id`, `access_token`, `api_version`
- [ ] Implement `start()`: validate credentials, verify API connectivity (optional: send test API call)
- [ ] Implement `stop()`: close httpx client, cleanup

### Task 2.2: Channel management

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [ ] `create_channel()` — Store customer phone number in WhatsApp adapter metadata; no platform-side channel creation (WhatsApp conversations are implicit)
- [ ] `update_channel_title()` — No-op, return True (WhatsApp has no channel concept)
- [ ] `close_channel()` — Mark session as closed in metadata, return True
- [ ] `reopen_channel()` — Clear closed flag, return True
- [ ] `delete_channel()` — No-op, return True
- [ ] `ensure_channel()` — Ensure phone number is stored in metadata; skip non-customer sessions

### Task 2.3: Outbound messaging

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [ ] `send_message()` — POST text message to `https://graph.facebook.com/{api_version}/{phone_number_id}/messages`
  - Payload: `{"messaging_product": "whatsapp", "to": "{recipient}", "type": "text", "text": {"body": "..."}}`
  - Handle message splitting for texts > 4096 chars
  - Track 24h window: if outside window, use template message
  - Return WhatsApp message ID (`wamid`)
- [ ] `edit_message()` — Return False (WhatsApp does not support message editing)
- [ ] `delete_message()` — Return False (WhatsApp does not support message deletion)
- [ ] `send_file()` — Upload media via POST `/{phone_number_id}/media`, then send media message referencing the `media_id`
  - Support images (image/jpeg, image/png), documents, audio
  - Caption limited to 1024 chars
- [ ] `get_max_message_length()` — Return 4096

### Task 2.4: Typing indicator and read receipts

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [ ] `send_typing_indicator()` — POST to messages endpoint with `{"messaging_product": "whatsapp", "status": "read", "message_id": "{last_received_message_id}"}`
- [ ] Store last received message ID in adapter metadata for read receipt targeting
- [ ] Fire-and-forget pattern: catch all exceptions, log at debug level

### Task 2.5: Platform-specific overrides

**File(s):** `teleclaude/adapters/whatsapp_adapter.py`

- [ ] `_convert_markdown_for_platform()` — Convert markdown to WhatsApp format:
  - Bold: `**text**` → `*text*`
  - Italic: `*text*` or `_text_` → `_text_`
  - Strikethrough: `~~text~~` → `~text~`
  - Code: `` `text` `` → ` ```text``` `
  - Strip unsupported formatting (headings, links with display text, images)
- [ ] `_fit_output_to_limit()` — Truncate output to 4096 chars with truncation indicator
- [ ] `_build_output_metadata()` — Return empty dict (no inline keyboards on WhatsApp)
- [ ] `format_output()` — Apply WhatsApp markdown conversion to tmux output

### Task 2.6: Adapter registration

**File(s):** `teleclaude/core/adapter_client.py`

- [ ] Add WhatsApp adapter startup in `AdapterClient.start()`:
  - Check if WhatsApp config is enabled and credentials present
  - Instantiate `WhatsAppAdapter(self)`
  - Call `await whatsapp.start()`
  - Register in `self.adapters["whatsapp"]`
  - Log startup success
- [ ] Import `WhatsAppAdapter` at module level

---

## Phase 3: Inbound Message Handling

### Task 3.1: WhatsApp normalizer

**File(s):** `teleclaude/hooks/normalizers/whatsapp.py` (new)

- [ ] Implement `normalize_whatsapp_webhook(payload: dict, headers: dict) -> list[HookEvent]`:
  - Parse Meta's nested structure: `entry[].changes[].value`
  - Handle message types: `text`, `image`, `document`, `audio`, `voice`, `video`
  - Handle status updates: `sent`, `delivered`, `read` (ignore or log)
  - Extract sender phone number, message ID, timestamp
  - Return list of `HookEvent` (one per message in payload; Meta can batch)
  - Source: `"whatsapp"`, Type: `"message.text"`, `"message.image"`, `"message.voice"`, etc.
- [ ] Register normalizer in `NormalizerRegistry` during daemon startup

### Task 3.2: Inbound message handler

**File(s):** `teleclaude/hooks/handlers/whatsapp.py` (new)

- [ ] Implement `handle_whatsapp_event(event: HookEvent) -> None`:
  - Extract phone number from event properties
  - Resolve identity: `whatsapp:{phone_number}` → person lookup
  - Find existing session for this phone number or create new customer session
  - Route by message type:
    - Text → inject as user message into session
    - Image/document → download media, save to workspace, dispatch file command
    - Voice/audio → download media, dispatch voice command (Whisper transcription)
  - Update `last_customer_message_at` in adapter metadata (24h window tracking)
- [ ] Media download helper: `GET /{media_id}` for URL, then download file with access token in Authorization header
- [ ] Register as built-in global subscription handler

### Task 3.3: Webhook verification

**File(s):** `teleclaude/hooks/normalizers/whatsapp.py` or adapter

- [ ] WhatsApp verification challenge is handled by `InboundEndpointRegistry` GET handler (already supports `hub.verify_token`)
- [ ] Verify that existing GET handler matches WhatsApp's challenge format: `hub.mode=subscribe`, `hub.verify_token`, `hub.challenge`
- [ ] HMAC-SHA256 signature verification for POST payloads via `X-Hub-Signature-256` header

---

## Phase 4: Validation

### Task 4.1: Unit tests

**File(s):** `tests/unit/test_whatsapp_adapter.py` (new)

- [ ] Test outbound message sending (mock httpx)
- [ ] Test message splitting for long texts
- [ ] Test typing indicator / read receipt sending
- [ ] Test markdown conversion for WhatsApp format
- [ ] Test 24h window detection and template fallback
- [ ] Test media upload and send
- [ ] Test adapter metadata serialization roundtrip
- [ ] Test config validation and activation rules
- [ ] Test identity resolution with WhatsApp phone numbers

### Task 4.2: Integration tests

**File(s):** `tests/integration/test_whatsapp_flow.py` (new)

- [ ] Test normalizer: raw Meta webhook payload → HookEvent list
- [ ] Test handler: HookEvent → session creation → message injection (mocked adapter)
- [ ] Test end-to-end: webhook → normalizer → handler → adapter response (all mocked external calls)
- [ ] Test voice message flow: webhook → download → transcription → session

### Task 4.3: Quality checks

- [ ] Run `make test` — all tests pass
- [ ] Run `make lint` — no new violations
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm all requirements traced to implementation tasks
- [ ] Confirm all implementation tasks marked `[x]`
- [ ] Document any deferrals in `deferrals.md` (if applicable)
- [ ] Confirm adapter metadata model is consistent with Telegram/Discord patterns
- [ ] Confirm no hardcoded credentials or secrets in code
