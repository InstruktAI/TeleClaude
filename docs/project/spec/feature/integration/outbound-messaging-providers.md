---
id: project/spec/feature/integration/outbound-messaging-providers
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Provider-specific send helpers for Telegram, Discord, WhatsApp Cloud API, and email (Brevo SMTP) — used by notification delivery adapters and the invitation flow.
---

# Outbound Messaging Providers — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

Four single-purpose async send functions, one per outbound channel:

- `send_telegram_dm(chat_id, content, file=None, *, token_env, timeout_s)`
- `send_discord_dm(user_id, content, *, token_env, timeout_s)`
- `send_whatsapp_message(phone_number, content, *, phone_number_id, access_token, api_version, timeout_s)`
- `send_email(to, subject, html_body, text_body=None, *, smtp_host, smtp_port)`

Each is a thin HTTP/SMTP client invocation: read credentials (from env
or kwargs), validate inputs, truncate long content to the channel's
hard limit (with a warning), POST/SMTP the message, parse the response,
and return the provider's message identifier (or `None` for SMTP). They
are NOT subscribers and NOT dispatchers — they are pure delivery
primitives that adapter classes and one-off callers (invitations) wrap.

In v1 production the Telegram, Discord, and WhatsApp helpers are wired
into `TelegramDeliveryAdapter` / `DiscordDeliveryAdapter` /
`WhatsAppDeliveryAdapter` push callbacks registered for each
admin-with-credentials at daemon startup. The email helper is called
directly from `teleclaude/invite.py` to send invitation links.

## Canonical fields

### Use cases

#### UC-MP1: Telegram DM (text)

```gherkin
Given TELEGRAM_BOT_TOKEN is set in the environment
When send_telegram_dm("12345", "Hello world") is awaited
Then a POST to https://api.telegram.org/bot<token>/sendMessage with form-encoded {chat_id, text, disable_web_page_preview:true} is sent
And on HTTP 2xx with response.json()["ok"] == true: returns str(result["message_id"])
And on text length > 4000: the text is truncated and a warning "message truncated" is logged
```

#### UC-MP2: Telegram document with caption

```gherkin
Given send_telegram_dm("12345", "Caption text", file="/tmp/report.pdf") is awaited
And the file exists and is a regular file
When the call runs
Then mimetypes.guess_type("report.pdf") yields ("application/pdf", None)
And a POST to sendDocument is sent as multipart/form-data with data={chat_id, caption} and files={document: (filename, fp, mime_type)}
And caption is truncated to 1024 chars (Telegram caption limit) with a warning when exceeded
And on success: returns the message_id
Otherwise (file missing): raises FileNotFoundError
Otherwise (not a file): raises ValueError
```

#### UC-MP3: Discord DM (create-channel-then-send)

```gherkin
Given DISCORD_BOT_TOKEN is set
When send_discord_dm("user-id-1", "hi") is awaited
Then POST /api/v10/users/@me/channels with {recipient_id: "user-id-1"} creates a DM channel
And channel_id is extracted from the response
And POST /api/v10/channels/<channel_id>/messages with {content: "hi"} sends the message
And on success: returns str(response.json()["id"])
And content > 2000 chars is truncated with a warning
And on 403 from create-channel: raises RuntimeError with the API detail (bot must share a guild with the user — platform limitation, not code)
```

#### UC-MP4: WhatsApp Cloud API send

```gherkin
Given access_token, phone_number_id, api_version are provided
When send_whatsapp_message("31612345678", "hi", phone_number_id=..., access_token=...) is awaited
Then a POST to https://graph.facebook.com/<api_version>/<phone_number_id>/messages with body {messaging_product: "whatsapp", to, type: "text", text: {body}} is sent
And on success: returns str(messages[0].id) from the JSON response
And content > 4096 chars is truncated with a warning
And on 4xx/5xx: raises RuntimeError with the API error message
```

#### UC-MP5: Email via Brevo SMTP

```gherkin
Given BREVO_SMTP_USER, BREVO_SMTP_PASS, BREVO_SENDER_EMAIL are set
When send_email("alice@example.com", "Subject", "<p>HTML body</p>") is awaited
Then a MIMEMultipart "alternative" message is built
And if text_body is omitted, a plain-text fallback is derived from the HTML by stripping tags
And asyncio.to_thread runs the SMTP sequence: connect (host, port, timeout=10), starttls, login, sendmail, close
And on success: logs "Email sent to <addr>: <subject>"
And on SMTP error: raises RuntimeError with the underlying exception chained
And BREVO_SENDER_NAME env var (default "TeleClaude") becomes the From: display name
```

#### UC-MP6: Missing credentials raise ValueError

```gherkin
Given the relevant env var or kwarg is missing or empty
When the send function runs its credential check
Then it raises ValueError("Missing <provider> token") or ValueError("Missing required Brevo SMTP credentials: ...")
And no network call is attempted
```

#### UC-MP7: Empty content rejected

```gherkin
Given content is empty or whitespace-only and no file is provided (for telegram)
When the send function evaluates inputs
Then it raises ValueError("Notification content is empty")
```

#### UC-MP8: HTTP client closed safely across event-loop shutdown

```gherkin
Given the daemon is shutting down and the underlying event loop is closing
When _close_client awaits httpx.AsyncClient.aclose
And the close raises RuntimeError("Event loop is closed")
Then the helper catches that specific RuntimeError
And logs a warning "<provider> http client close hit closed loop"
And returns normally (other RuntimeErrors propagate)
```

### Implementation pointers (v1)

- `teleclaude/services/telegram.py` —
  `send_telegram_dm` (L34),
  `_close_client` (L19),
  constants `DEFAULT_MESSAGE_MAX_LENGTH=4000`,
  `DEFAULT_CAPTION_MAX_LENGTH=1024` (file head).
- `teleclaude/services/discord.py` —
  `send_discord_dm` (L38),
  `_close_client` (L23),
  `DISCORD_MAX_MESSAGE_LENGTH=2000`,
  `DISCORD_API_BASE="https://discord.com/api/v10"` (file head).
- `teleclaude/services/whatsapp.py` —
  `send_whatsapp_message` (L36),
  `_close_client` (L21),
  `WHATSAPP_MAX_MESSAGE_LENGTH=4096` (file head).
- `teleclaude/services/email.py` —
  `send_email` (L17, synchronous SMTP wrapped in `asyncio.to_thread`).
- `teleclaude/daemon_event_platform.py` — registration helpers:
  `_register_telegram_delivery_callbacks` (L157),
  `_register_discord_delivery_callbacks` (L179),
  `_register_whatsapp_delivery_callbacks` (L202),
  invoked from `_build_push_callbacks` (L140) at startup.
- `teleclaude/events/delivery/discord.py`,
  `teleclaude/events/delivery/whatsapp.py`,
  `teleclaude/events/delivery/telegram.py` (in
  `teleclaude/notifications` family) — the wrapping delivery adapters
  that orchestrate per-admin push.
- `teleclaude/invite.py` — `send_email` consumer for invitations
  (L242 in the invite send flow).

### Cross-context references

- Consumers in `agent_runtime` / notification subsystems push to these
  helpers via per-admin adapters; the delivery adapter classes
  enforce per-recipient routing, shutdown checks, and per-channel
  formatting.
- The v2 domain spec consolidates these provider sends behind a
  channel-cascade dispatcher (`docs/project/spec/domain/integration.md`
  `OutboxEntry.cascade` + the dispatcher worker). v1 has no
  cascade fallback at the send-function layer — each helper is direct
  send only; cascade is the adapter's responsibility (if any).
- Inbound counterpart (WhatsApp) is
  `whatsapp-inbound-conversation-routing` and the WhatsApp inbound
  normalizer; these outbound helpers share no code with inbound paths.

## Known caveats

- **Direct send, no outbox.** These helpers do NOT go through the
  webhook_outbox or any retry queue. A 5xx from Telegram is reported
  as a RuntimeError to the caller; retry policy (if any) lives in the
  delivery adapter layer above. In v2 these become per-channel
  attempts inside the outbox cascade.
- **Discord DM 403 (no shared guild).** Discord's API requires the
  bot and recipient to share at least one guild before a DM channel
  can be opened. There is no workaround in code — the caller must
  ensure the bot is invited to a guild containing the recipient.
- **WhatsApp 24-hour session window.** WhatsApp Cloud API rejects
  free-form text after the 24-hour window has closed (since the last
  inbound from the recipient). The helper does not pre-check the
  window; failures surface as RuntimeError from the API.
- **Email plain-text fallback is regex stripping**, not a proper HTML
  → text converter. Recipients with text-only mail clients may see
  artifacts.
- **All helpers truncate at the provider hard limit with a warning**
  rather than splitting into chained messages. Long bodies risk
  losing trailing content.
- **No per-helper rate limiting.** A burst of admin notifications can
  hit provider rate limits (especially Discord's per-bot limits). The
  delivery adapter layer is expected to coalesce or throttle.
- **Email subject/sender display configured via env vars only** —
  there is no per-message override in v1; the helper reads
  `BREVO_SENDER_NAME` and `BREVO_SENDER_EMAIL` once per send.
- **Telegram returns the message id as int** in the API; the helper
  casts to `str` for consistency with Discord/WhatsApp which return
  string ids.
