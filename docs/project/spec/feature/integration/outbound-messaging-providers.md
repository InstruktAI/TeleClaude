---
id: 'project/spec/feature/integration/outbound-messaging-providers'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Provider-specific send helpers for Telegram, Discord, WhatsApp Cloud API, and email (Brevo SMTP) — used by notification delivery adapters and the invitation flow.'
---

# Outbound Messaging Providers — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

Four single-purpose send capabilities, one per outbound channel:

- Telegram direct message (text or document with caption)
- Discord direct message
- WhatsApp Cloud API message
- Email via Brevo SMTP

Each is a thin provider-client invocation: read credentials (from env
or call arguments), validate inputs, truncate long content to the
channel's hard limit (with a warning), submit the message to the
provider, parse the response, and return the provider's message
identifier (or nothing for SMTP). They are NOT subscribers and NOT
dispatchers — they are pure delivery primitives that adapter classes
and one-off callers (invitations) wrap.

In v1 production the Telegram, Discord, and WhatsApp helpers are wired
into per-provider delivery adapters registered for each admin-with-
credentials at integration service startup. The email helper is called
directly from the invitation flow to send invitation links.

## Canonical fields

### Use cases

#### UC-MP1: Telegram DM (text)

```gherkin
Given the Telegram bot token is configured
When send-telegram-dm is invoked for chat "12345" with text "Hello world"
Then the Telegram send-message endpoint receives the message with link previews disabled
And on a successful response the helper returns the message id as a string
And on text length above 4000 characters: the text is truncated and a warning "message truncated" is logged
```

#### UC-MP2: Telegram document with caption

```gherkin
Given send-telegram-dm is invoked for chat "12345" with caption "Caption text" and file "/tmp/report.pdf"
And the file exists and is a regular file
When the call runs
Then the mime type is inferred from the filename ("application/pdf")
And the Telegram send-document endpoint receives the file as multipart with caption metadata
And caption is truncated to 1024 characters (Telegram caption limit) with a warning when exceeded
And on success: returns the message id
Otherwise (file missing): raises a not-found error
Otherwise (not a file): raises an invalid-argument error
```

#### UC-MP3: Discord DM (create-channel-then-send)

```gherkin
Given the Discord bot token is configured
When send-discord-dm is invoked for user "user-id-1" with content "hi"
Then a DM channel is opened with the recipient
And the message is sent on that channel
And on success: returns the message id as a string
And content above 2000 characters is truncated with a warning
And on a forbidden response from channel creation: raises an error reflecting the API detail (the bot must share a guild with the user — platform limitation, not code)
```

#### UC-MP4: WhatsApp Cloud API send

```gherkin
Given access token, phone-number id, and API version are provided
When send-whatsapp-message is invoked for "31612345678" with content "hi"
Then a WhatsApp Cloud API text message is submitted under the configured phone-number id
And on success: returns the first message id from the response
And content above 4096 characters is truncated with a warning
And on a client or server error response: raises an error with the API error message
```

#### UC-MP5: Email via Brevo SMTP

```gherkin
Given the Brevo SMTP credentials and sender email are configured
When send-email is invoked for "alice@example.com" with subject and HTML body
Then a multipart "alternative" message is built
And if a plain-text body is omitted, a fallback is derived from the HTML by stripping tags
And the SMTP send sequence runs off the main loop: connect, STARTTLS, login, send, close
And on success: logs "email sent to <addr>: <subject>"
And on SMTP error: raises an error with the underlying exception chained
And the configured sender-name env var (default "TeleClaude") becomes the From display name
```

#### UC-MP6: Missing credentials raise an invalid-argument error

```gherkin
Given the relevant env var or call argument is missing or empty
When the send capability runs its credential check
Then it raises an invalid-argument error ("missing <provider> token" or "missing required Brevo SMTP credentials: ...")
And no provider call is attempted
```

#### UC-MP7: Empty content rejected

```gherkin
Given content is empty or whitespace-only and no file is provided (for Telegram)
When the send capability evaluates inputs
Then it raises an invalid-argument error ("notification content is empty")
```

#### UC-MP8: Provider client closed safely across shutdown

```gherkin
Given the integration service is shutting down and the underlying event loop is closing
When the per-provider client is closed
And the close raises an "event loop is closed" runtime error
Then the helper catches that specific runtime error
And logs a warning "<provider> client close hit closed loop"
And returns normally (other runtime errors propagate)
```

### Cross-context references

- Consumers in `agent_runtime` and the notification subsystem push to
  these capabilities via per-admin delivery adapters; the adapter
  classes enforce per-recipient routing, shutdown checks, and per-
  channel formatting.
- The v2 domain spec consolidates these provider sends behind a
  channel-cascade dispatcher (see `docs/project/spec/domain/integration.md`
  Outbox Entry cascade and the dispatcher worker). v1 has no cascade
  fallback at the send-capability layer — each helper is direct send
  only; cascade is the adapter's responsibility (if any).
- Inbound counterpart (WhatsApp) is
  `whatsapp-inbound-conversation-routing` and the WhatsApp inbound
  normalizer; these outbound helpers share no code with inbound paths.

## Known caveats

- **Direct send, no outbox.** These capabilities do NOT go through the
  webhook outbox or any retry queue. A server error from Telegram is
  reported to the caller; retry policy (if any) lives in the delivery
  adapter layer above. In v2 these become per-channel attempts inside
  the outbox cascade.
- **Discord DM forbidden (no shared guild).** Discord's API requires
  the bot and recipient to share at least one guild before a DM channel
  can be opened. There is no workaround in code — the caller must
  ensure the bot is invited to a guild containing the recipient.
- **WhatsApp 24-hour session window.** The WhatsApp Cloud API rejects
  free-form text after the 24-hour window has closed (since the last
  inbound from the recipient). The helper does not pre-check the
  window; failures surface as runtime errors from the API.
- **Email plain-text fallback is regex stripping**, not a proper HTML →
  text converter. Recipients with text-only mail clients may see
  artifacts.
- **All helpers truncate at the provider hard limit with a warning**
  rather than splitting into chained messages. Long bodies risk losing
  trailing content.
- **No per-helper rate limiting.** A burst of admin notifications can
  hit provider rate limits (especially Discord's per-bot limits). The
  delivery adapter layer is expected to coalesce or throttle.
- **Email subject and sender display configured via env vars only** —
  there is no per-message override in v1; the helper reads sender-name
  and sender-email once per send.
- **Telegram returns the message id as an integer** in the API; the
  helper casts to a string for consistency with Discord and WhatsApp,
  which return string ids.
