---
id: 'project/spec/feature/integration/whatsapp-inbound-conversation-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'End-to-end inbound WhatsApp pipeline — normalize the Cloud API webhook payload, route via a built-in contract, resolve or create a session per phone number, and dispatch a typed command for text or media.'
---

# WhatsApp Inbound Conversation Routing — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The complete inbound path for WhatsApp messages: a normalizer that turns
the Cloud API webhook envelope into one HookEvent per message, a built-in
Contract (registered programmatically at daemon startup) that matches every
`whatsapp` source with a `message.*` type pattern and routes to the
internal `whatsapp_inbound` handler, and the handler itself which
resolves-or-creates a per-phone-number session, optionally downloads media
into the session workspace, and dispatches a typed command
(`ProcessMessageCommand`, `HandleFileCommand`, `HandleVoiceCommand`)
through the configured WhatsApp UI adapter so the session sees a
normalized user message.

The pipeline is the canonical example of v1's three-stage inbound design:
**framework registration** (inbound endpoint with normalizer key) →
**Contract / matcher routing** (built-in contract programmatically
registered for whatsapp → handler) → **internal handler** (session
resolution + command dispatch).

## Canonical fields

### Use cases

#### UC-WI1: Text message creates session and dispatches process_message

```gherkin
Given the daemon has a built-in contract id="builtin-whatsapp-inbound" routing source=whatsapp, type pattern message.* to handler "whatsapp_inbound"
And no existing session has origin_metadata.whatsapp.phone_number = "31612345678"
When WhatsApp POSTs a webhook with a text message from "31612345678" with body "hello"
And the inbound framework normalizes via normalize_whatsapp_webhook
And produces HookEvent(source="whatsapp", type="message.text", properties={phone_number, message_id, text})
And the dispatcher matches the built-in contract
And invokes handle_whatsapp_event(event)
Then _normalize_phone_number strips to digits
And _resolve_or_create_session finds no session
And TelecAPIClient.create_session is called with computer, help-desk project_path, default agent, origin=WHATSAPP, metadata={origin, origin_metadata: {phone_number, platform: whatsapp}}
And the new session_id is returned and the session row loaded
And _update_whatsapp_session_metadata writes origin_metadata.whatsapp = {phone_number, last_received_message_id, last_customer_message_at}
And _handle_text_event builds ProcessMessageCommand(session_id, text="hello", origin=WHATSAPP, actor_id="whatsapp:31612345678", actor_name="31612345678")
And _dispatch_whatsapp_command routes through the WhatsApp UiAdapter's _dispatch_command with MessageMetadata
And the command service's process_message handler runs
```

#### UC-WI2: Existing session is reused for the same phone number

```gherkin
Given an active session has origin_metadata.whatsapp.phone_number = "31612345678"
When a new text message arrives from "31612345678"
Then db.get_sessions_by_origin_metadata("whatsapp", "phone_number", "31612345678") returns the existing session
And the resolve step returns it (the first match)
And no new session is created
And origin_metadata is refreshed (last_received_message_id, last_customer_message_at)
And the command dispatches to the same session
```

#### UC-WI3: Voice message downloads media as ogg into session voice/ directory

```gherkin
Given a WhatsApp voice message arrives with audio mime_type "audio/ogg; codecs=opus" and id "abc"
And session_id resolves to "sess-1"
When _handle_media_event runs for type="message.voice"
Then download_whatsapp_media is called
And _fetch_whatsapp_media_bytes does two HTTPS GETs against graph.facebook.com:
    1. GET /<api_version>/<media_id> → returns {url}
    2. GET <url> → returns media bytes
And _resolve_media_subdir returns "voice" for message.voice / message.audio types
And the file is written to <session_output_dir>/voice/<phone>_<YYYYMMDDHHMMSS>_<media_id_first_12>.ogg
And HandleVoiceCommand(session_id, file_path, origin=WHATSAPP, actor_id, actor_name) is dispatched
```

#### UC-WI4: Image message downloads into photos/ as HandleFileCommand

```gherkin
Given a WhatsApp image message arrives with media id "img-1" and mime_type "image/jpeg"
When _handle_media_event runs for type="message.image"
Then _resolve_media_subdir returns "photos"
And the file is downloaded as <phone>_<ts>_<id12>.jpg
And HandleFileCommand(session_id, file_path, filename, file_size) is dispatched
```

#### UC-WI5: Document message downloads into files/

```gherkin
Given a WhatsApp document arrives with media id "doc-1" and mime_type "application/pdf"
When _handle_media_event runs for type="message.document"
Then _resolve_media_subdir returns "files" (default for non-image, non-voice)
And the file is downloaded with .pdf extension
And HandleFileCommand is dispatched
```

#### UC-WI6: WhatsApp UiAdapter unavailable falls back to direct handler call

```gherkin
Given the command service's client.adapters does not contain a "whatsapp" UiAdapter (e.g., disabled)
When _dispatch_whatsapp_command runs
Then it detects adapters is missing or not a UiAdapter for WHATSAPP
And calls handler() directly without UI adapter routing
And the command still executes
```

#### UC-WI7: Missing phone_number drops the event

```gherkin
Given a normalized HookEvent has empty or missing phone_number property
When handle_whatsapp_event runs
Then a warning "WhatsApp event missing phone_number" is logged
And the handler returns without further action
```

#### UC-WI8: Session creation failure drops the event

```gherkin
Given TelecAPIClient.create_session returns a result with empty session_id
When _resolve_or_create_session evaluates the result
Then it logs "WhatsApp session creation returned empty session_id"
And returns None
And handle_whatsapp_event returns silently with no command dispatch
```

#### UC-WI9: WhatsApp Cloud API timestamp normalization

```gherkin
Given the inbound message carries timestamp = "1700000000" (Unix seconds as string)
When _to_event_timestamp runs in the normalizer
Then it parses the integer and returns datetime.fromtimestamp(..., UTC).isoformat()
And the HookEvent.timestamp is the converted ISO 8601 form
Otherwise (non-numeric or missing): falls back to datetime.now(UTC).isoformat()
```

#### UC-WI10: voice vs audio classification by mime type

```gherkin
Given an audio message with mime_type "audio/ogg; codecs=opus" and message type "voice"
When _message_type runs
Then the type "voice" maps to "message.voice"
Given mime_type contains "ogg" even with audio type
Then the message is classified as "message.voice"
Otherwise: classified as "message.audio"
```

### Implementation pointers (v1)

- `teleclaude/hooks/whatsapp_handler.py` —
  `handle_whatsapp_event` (L261, entry handler),
  `_resolve_or_create_session` (L35),
  `_update_whatsapp_session_metadata` (L68),
  `_dispatch_whatsapp_command` (L140),
  `_handle_text_event` (L183),
  `_handle_media_event` (L210),
  `download_whatsapp_media` (L114),
  `_fetch_whatsapp_media_bytes` (L89),
  `_resolve_media_subdir` (L105),
  `_normalize_phone_number` (L28).
- `teleclaude/hooks/normalizers/whatsapp.py` —
  `normalize_whatsapp_webhook` (L106),
  `_iter_whatsapp_messages` (L44),
  `_message_type` (L23),
  `_build_message_properties` (L89),
  `_extract_media_properties` (L73),
  `_normalize_phone` (L10),
  `_to_event_timestamp` (L16).
- `teleclaude/daemon_event_platform.py` (inside `_init_webhook_service`
  at L464) — programmatic registration of
  `Contract(id="builtin-whatsapp-inbound", target=
Target(handler="whatsapp_inbound"), source_criterion=match "whatsapp",
type_criterion=pattern "message.*", source="programmatic")` (~L482)
  and `handler_registry.register("whatsapp_inbound",
handle_whatsapp_event)` (~L481).
- `teleclaude/core/origins.py` — `InputOrigin.WHATSAPP`.
- `teleclaude/types/commands.py` — `ProcessMessageCommand`,
  `HandleVoiceCommand`, `HandleFileCommand`.
- `teleclaude/core/session_utils.py` — `get_session_output_dir`.
- WhatsApp Cloud API auth: `config.whatsapp.access_token`,
  `config.whatsapp.api_version`, `config.whatsapp.phone_number_id`.

### Cross-context references

- Inbound side of `outbound-messaging-providers`: the same provider
  (WhatsApp) is supported in both directions, but the inbound handler
  belongs to `integration` and the outbound `send_whatsapp_message`
  belongs to `integration` too. The session-creation step calls into
  `agent_runtime` via the daemon's API client.
- Uses `eventbus-hook-bridge`'s HookDispatcher and Contract matcher.
- Touches `agent_runtime` to create sessions (cross-context call via
  the API client).
- Touches `identity` indirectly through origin_metadata, which the
  identity context reads to resolve principal-from-origin.

## Known caveats

- The WhatsApp Cloud API enforces a 24-hour messaging window for
  non-template outbound messages; this constraint is enforced on the
  outbound side (`outbound-messaging-providers`), not here, but it
  shapes the asymmetric send/receive lifecycle.
- The media-download step writes directly to disk under
  `get_session_output_dir(session_id)` without staging — failures mid-
  download leave partial files in the workspace. v1 has no retry on
  the media fetch. Exceptions from `handle_whatsapp_event` are caught
  inside `HookDispatcher.dispatch`'s per-Contract try/except (logged as
  "Internal handler failed") and do NOT escape back to the inbound
  framework; the HTTP response remains `{"status": "accepted"}` with 200. Redelivery does NOT happen automatically — WhatsApp considers
  the webhook accepted. Operators must look at daemon error logs to
  observe these failures.
- Phone numbers are normalized by stripping non-digits before lookup,
  storage, and outbound — `+31 6 1234 5678` and `0031612345678` map to
  the same `31612345678` identity (a known equivalence quirk).
- The handler uses the first session returned by
  `get_sessions_by_origin_metadata` (sessions[0]) when multiple
  sessions share a phone number — selection is implicit and
  order-dependent.
- The built-in contract uses `source="programmatic"` (not
  `source="config"`), distinguishing it from contracts loaded via the
  YAML subscriptions section. The HTTP API also exposes this contract
  in list/properties responses.
- `_dispatch_whatsapp_command` invokes `adapter._dispatch_command`
  (a private method) directly — a deliberate v1 escape from the public
  command API to inject WhatsApp-specific metadata (platform_message_id,
  actor_avatar_url) without changing the command type surface.
- Image type detection prefers the explicit message.image classification
  but falls back to checking mime_type startswith "image/"; documents
  and unknown media types land in `files/`.
- v1 does NOT verify the WhatsApp signature at the handler layer — that
  is the inbound framework's responsibility via the inbound `secret`
  config (see `inbound-webhook-endpoint-framework`).
