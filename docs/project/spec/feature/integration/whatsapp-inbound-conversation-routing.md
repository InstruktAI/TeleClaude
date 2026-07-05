---
description: 'End-to-end inbound WhatsApp pipeline — normalize the Cloud API webhook payload, route via a built-in contract, resolve or create a session per phone number, and dispatch a typed command for text or media.'
visibility: 'public'
---

# WhatsApp Inbound Conversation Routing — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

The complete inbound path for WhatsApp messages: a normalizer that
turns the Cloud API webhook envelope into one hook event per message, a
built-in contract (registered programmatically at integration service
startup) that matches every `whatsapp` source with a `message.*` type
pattern and routes to the internal `whatsapp_inbound` handler, and the
handler itself which resolves-or-creates a per-phone-number session,
optionally downloads media into the session workspace, and dispatches a
typed command (process-message, handle-file, or handle-voice) through
the configured WhatsApp UI adapter so the session sees a normalized
user message.

The pipeline is the canonical example of v1's three-stage inbound
design: **framework registration** (inbound endpoint with normalizer
key) → **contract / matcher routing** (built-in contract programmatically
registered for whatsapp → handler) → **internal handler** (session
resolution + command dispatch).

## Canonical fields

### Use cases

<!-- planned-change:whatsapp-inbound-transport-rewire -->

#### UC-WI1: Text message creates session and dispatches process-message

```gherkin
Given the integration service has a built-in contract id="builtin-whatsapp-inbound" routing source=whatsapp, type pattern message.* to handler "whatsapp_inbound"
And no existing session has origin-metadata.whatsapp.phone_number = "31612345678"
When WhatsApp delivers a webhook with a text message from "31612345678" with body "hello"
And the inbound framework normalizes via the WhatsApp normalizer
And produces a hook event(source="whatsapp", type="message.text", properties={phone_number, message_id, text})
And the dispatcher matches the built-in contract
And invokes the WhatsApp inbound handler
Then phone-number normalization strips to digits
And the session resolver finds no session
And the platform's session-create API is called with computer, help-desk project path, default agent, origin=WHATSAPP, and metadata carrying the WhatsApp origin and phone number
And the new session id is returned and the session record loaded
And the WhatsApp session metadata is recorded (phone number, last received message id, last customer message timestamp)
And the text handler builds a process-message command(session id, text="hello", origin=WHATSAPP, actor id="whatsapp:31612345678", actor name="31612345678")
And the command is routed through the WhatsApp UI adapter with message metadata
And the command service's process-message handler runs
```

<!-- change:whatsapp-inbound-transport-rewire -->

#### UC-WI1: Text message creates session and dispatches process-message

```gherkin
Given the integration service has a built-in contract id="builtin-whatsapp-inbound" routing source=whatsapp, type pattern message.* to handler "whatsapp_inbound"
And no existing session has origin-metadata.whatsapp.phone_number = "31612345678"
When WhatsApp delivers a webhook with a text message from "31612345678" with body "hello"
And the inbound framework normalizes via the WhatsApp normalizer
And produces a hook event(source="whatsapp", type="message.text", properties={phone_number, message_id, text})
And the dispatcher matches the built-in contract
And invokes the WhatsApp inbound handler
Then phone-number normalization strips to digits
And the session resolver finds no session via the by-origin-metadata lookup
And the handler resolves-or-creates the session through the shared core inbound seam, calling the core session-create command in-process (no HTTP loopback) with the help-desk project path, default agent, origin=WHATSAPP, and origin metadata carrying the phone number
And the created session id is returned and the session record loaded
And the WhatsApp session metadata is recorded (phone number, last received message id, last customer message timestamp)
And the text handler builds a process-message command(session id, text="hello", origin=WHATSAPP, actor id="whatsapp:31612345678", actor name="31612345678")
And the command is dispatched through the WhatsApp UI adapter's public dispatch path with message metadata
And the command service's process-message handler runs
```

<!-- /planned-change:whatsapp-inbound-transport-rewire -->

#### UC-WI2: Existing session is reused for the same phone number

```gherkin
Given an active session has origin-metadata.whatsapp.phone_number = "31612345678"
When a new text message arrives from "31612345678"
Then the by-origin-metadata lookup ("whatsapp", "phone_number", "31612345678") returns the existing session
And the resolver returns it (the first match)
And no new session is created
And origin metadata is refreshed (last received message id, last customer message timestamp)
And the command dispatches to the same session
```

#### UC-WI3: Voice message downloads media as ogg into session voice/ directory

```gherkin
Given a WhatsApp voice message arrives with audio mime type "audio/ogg; codecs=opus" and id "abc"
And the session id resolves to "sess-1"
When the media handler runs for type="message.voice"
Then the WhatsApp media download is invoked
And the fetch performs two authenticated requests against the WhatsApp Cloud API:
    1. retrieve the media URL by id
    2. retrieve the media bytes from that URL
And the media subdirectory resolver returns "voice" for message.voice / message.audio types
And the file is written to <session output dir>/voice/<phone>_<YYYYMMDDHHMMSS>_<media id first 12>.ogg
And a handle-voice command(session id, file path, origin=WHATSAPP, actor id, actor name) is dispatched
```

#### UC-WI4: Image message downloads into photos/ as handle-file command

```gherkin
Given a WhatsApp image message arrives with media id "img-1" and mime type "image/jpeg"
When the media handler runs for type="message.image"
Then the media subdirectory resolver returns "photos"
And the file is downloaded as <phone>_<ts>_<id12>.jpg
And a handle-file command(session id, file path, filename, file size) is dispatched
```

#### UC-WI5: Document message downloads into files/

```gherkin
Given a WhatsApp document arrives with media id "doc-1" and mime type "application/pdf"
When the media handler runs for type="message.document"
Then the media subdirectory resolver returns "files" (default for non-image, non-voice)
And the file is downloaded with .pdf extension
And a handle-file command is dispatched
```

#### UC-WI6: WhatsApp UI adapter unavailable falls back to direct handler call

```gherkin
Given the command service's adapter set does not contain a WhatsApp UI adapter (e.g., disabled)
When the WhatsApp-command router runs
Then it detects the adapter is missing or not a WhatsApp UI adapter
And calls the command handler directly without UI adapter routing
And the command still executes
```

#### UC-WI7: Missing phone-number drops the event

```gherkin
Given a normalized hook event has an empty or missing phone-number property
When the WhatsApp handler runs
Then a warning "WhatsApp event missing phone_number" is logged
And the handler returns without further action
```

#### UC-WI8: Session creation failure drops the event

```gherkin
Given the session-create API returns a result with an empty session id
When the resolver evaluates the result
Then it logs "WhatsApp session creation returned empty session_id"
And returns nothing
And the WhatsApp handler returns silently with no command dispatch
```

#### UC-WI9: WhatsApp Cloud API timestamp normalization

```gherkin
Given the inbound message carries timestamp = "1700000000" (Unix seconds as string)
When the event-timestamp normalizer runs
Then it parses the integer and returns the UTC ISO 8601 form
And the hook event timestamp is the converted ISO 8601 form
Otherwise (non-numeric or missing): falls back to the current UTC time in ISO 8601
```

#### UC-WI10: voice vs audio classification by mime type

```gherkin
Given an audio message with mime type "audio/ogg; codecs=opus" and message type "voice"
When the message-type classifier runs
Then the type "voice" maps to "message.voice"
Given mime type contains "ogg" even with audio type
Then the message is classified as "message.voice"
Otherwise: classified as "message.audio"
```

### Cross-context references

- Inbound side of `outbound-messaging-providers`: the same provider
  (WhatsApp) is supported in both directions, but the inbound handler
  belongs to `integration` and the outbound send capability also
  belongs to `integration`. The session-creation step calls into
  `agent_runtime` via the platform's session-create API.
- Uses `eventbus-hook-bridge`'s hook dispatcher and contract matcher.
- Touches `agent_runtime` to create sessions (cross-context call via
  the platform API).
- Touches `identity` indirectly through origin metadata, which the
  identity context reads to resolve principal-from-origin.

## Known caveats

- The WhatsApp Cloud API enforces a 24-hour messaging window for
  non-template outbound messages; this constraint is enforced on the
  outbound side (`outbound-messaging-providers`), not here, but it
  shapes the asymmetric send/receive lifecycle.
- The media-download step writes directly into the session workspace
  without staging — failures mid-download leave partial files in the
  workspace. v1 has no retry on the media fetch. Exceptions from the
  WhatsApp handler are caught inside the dispatcher's per-contract
  guard (logged as "internal handler failed") and do NOT escape back
  to the inbound framework; the inbound response remains accepted.
  Redelivery does NOT happen automatically — WhatsApp considers the
  webhook accepted. Operators must look at error logs to observe
  these failures.
- Phone numbers are normalized by stripping non-digits before lookup,
  storage, and outbound — `+31 6 1234 5678` and `0031612345678` map to
  the same `31612345678` identity (a known equivalence quirk).
- The handler uses the first session returned by the by-origin-metadata
  lookup when multiple sessions share a phone number — selection is
  implicit and order-dependent.
- The built-in contract uses source "programmatic" (not source
  "config"), distinguishing it from contracts loaded via the YAML
  subscriptions section. The management API also exposes this contract
  in list and properties responses.

<!-- planned-change:whatsapp-inbound-transport-rewire -->

- The WhatsApp-command router invokes a private dispatch method on the
  adapter directly — a deliberate v1 escape from the public command
  API to inject WhatsApp-specific metadata (platform message id, actor
  avatar URL) without changing the command type surface.

<!-- change:whatsapp-inbound-transport-rewire -->

- The WhatsApp-command router dispatches inbound commands through the
  WhatsApp UI adapter's public dispatch path, injecting WhatsApp-specific
  metadata (platform message id, actor avatar URL) without changing the
  command type surface. When no WhatsApp UI adapter is present it falls
  back to calling the command handler directly (UC-WI6).

<!-- /planned-change:whatsapp-inbound-transport-rewire -->

- Image type detection prefers the explicit message.image
  classification but falls back to checking mime type starts-with
  "image/"; documents and unknown media types land in `files/`.
- v1 does NOT verify the WhatsApp signature at the handler layer —
  that is the inbound framework's responsibility via the inbound
  `secret` config (see `inbound-webhook-endpoint-framework`).
