---
description: 'Provider-specific send helpers for Telegram, Discord, WhatsApp Cloud API, and email (Brevo SMTP) — used by notification delivery adapters and the invitation flow.'
visibility: 'public'
---

# Outbound Messaging Providers — Spec

## What it is

Four single-purpose send capabilities, one per outbound channel:

- Telegram direct message (text or document with caption)
- Discord direct message (text or file attachment with accompanying text)
- WhatsApp Cloud API message
- Email via Brevo SMTP (HTML with optional plain-text alternative and file attachments)

Each is a thin provider-client invocation: read credentials from the typed
machine-config aggregate (or an explicit per-call argument), validate inputs,
truncate long content to the channel's hard limit where supported, submit the message to the
provider, parse the response, and return the provider's message
identifier (or nothing for SMTP). They are NOT subscribers and NOT
dispatchers — they are pure delivery primitives that adapter classes
and one-off callers (invitations) wrap.

In v1 production the Telegram, Discord, and WhatsApp helpers are wired
into per-provider delivery adapters registered for each admin-with-
credentials at integration service startup. The email helper is called
directly from the invitation flow to send invitation links.

Telegram text sends disable link previews. Email sends an HTML body with a
plain-text alternative; when no plain-text body is supplied, it is derived from
the HTML. Attachments must be existing regular files, and their MIME type is
inferred from the filename. Telegram, Discord and WhatsApp reject missing
credentials before provider calls; missing email credentials reach SMTP login
and surface as a send error. Empty Telegram text without an attachment is
rejected. Telegram, Discord and WhatsApp truncate long text or captions at the
provider's hard limit with a warning and do not split messages; email sends the
complete body. Successful API sends return the provider's message identifier;
SMTP returns none. Provider failures are surfaced to the caller.

## Canonical fields

### Client shutdown

A provider client closing after its event loop is already closed logs a warning
and returns normally; other close errors remain visible to the caller.

### Use cases

#### UC-MP1: Telegram DM (text)

#### UC-MP2: Telegram document with caption

#### UC-MP3: Discord DM (create-channel-then-send)

#### UC-MP9: Discord DM with file attachment

#### UC-MP4: WhatsApp Cloud API send

#### UC-MP5: Email via Brevo SMTP

#### UC-MP10: Email with file attachment

#### UC-MP6: Missing credentials raise an invalid-argument error

#### UC-MP7: Empty content rejected

#### UC-MP8: Provider client closed safely across shutdown

### Cross-context references

- Consumers in `agent_runtime` and the notification subsystem push to
  these capabilities via per-admin delivery adapters; the adapter
  classes enforce per-recipient routing, shutdown checks, and per-
  channel formatting.
- The v2 domain spec consolidates these provider sends behind a
  channel-cascade dispatcher (see `docs/local/spec/domain/integration.md`
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
- **Telegram, Discord and WhatsApp truncate at the provider hard limit with a
  warning** rather than splitting into chained messages. Email sends the
  complete body without truncation.

- **No per-helper rate limiting.** A burst of admin notifications can
  hit provider rate limits (especially Discord's per-bot limits). The
  delivery adapter layer is expected to coalesce or throttle.

- **Email sender identity is machine configuration** — there is no per-message
  override in v1; the helper reads the typed sender and reply-to fields once per
  send.
- **Telegram returns the message id as an integer** in the API; the
  helper casts to a string for consistency with Discord and WhatsApp,
  which return string ids.
