---
description: 'End-to-end inbound WhatsApp pipeline — normalize the Cloud API webhook payload, route via a built-in contract, resolve or create a session per phone number, and dispatch a typed command for text or media.'
visibility: 'public'
---

# WhatsApp Inbound Conversation Routing — Spec

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

The pipeline has four stages: **the ingress endpoint** (the WhatsApp
source the global configuration declares, verified with Meta's
signature) → **the relay** (each message published to the cluster as
the platform event `whatsapp.message.<type>`, with no subject) →
**contract / matcher routing** (each computer delivers the relayed
message to its hook dispatcher as the normalized hook event, where the
built-in contract routes it to the handler) → **internal handler**
(session resolution + command dispatch). The endpoint and relay are
owned by `inbound-webhook-endpoint-framework` and
`single-ingress-webhook-termination`.

Every computer receives each message, and the mesh master alone decides where
it goes (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`);
no other computer handles it. A message whose text is exactly an entry
identifier is an entry: the core resolves it, and the number's session at that
endpoint on the master — continued, revived or created — becomes the session
the number's binding names. Any other message goes to the session the binding
names, revived when it was closed; with no binding, a registered person reaches
their own assistant and anyone else gets the neutral reply.

## Canonical fields

### Received message facts

The phone number is the conversation key. Each message updates the resolved
session's WhatsApp origin metadata with the provider message ID and timestamp.
The ID supports read receipts; the timestamp governs the 24-hour free-text
reply window. Provider timestamps in Unix seconds are normalized to UTC, with
the receive time used when a timestamp is missing or invalid. Voice messages
and Ogg/Opus audio are delivered as voice input; other audio, images and
documents are delivered as file input. A message without a phone number is
logged and not routed; if resolution returns no session, no command is
dispatched.

### Use cases

#### UC-WI1: Text message reaches the number's session and dispatches process-message

#### UC-WI2: Existing session is reused for the same phone number

#### UC-WI3: A person can send a voice message through WhatsApp

```gherkin
Given a person has a WhatsApp conversation bound to an assistant session
When they send a voice message
Then its audio reaches the bound session as voice input
```

#### UC-WI4: A person can send an attachment through WhatsApp

```gherkin
Scenario Outline: Send <attachment>
  Given a person has a WhatsApp conversation bound to an assistant session
  When they send a <attachment>
  Then it reaches the bound session as file input

  Examples:
    | attachment |
    | image      |
    | document   |
```

#### UC-WI5: Document message downloads into files/

#### UC-WI6: WhatsApp UI adapter unavailable falls back to direct handler call

#### UC-WI7: Missing phone-number drops the event

#### UC-WI8: Session creation failure drops the event

#### UC-WI9: WhatsApp Cloud API timestamp normalization

#### UC-WI10: voice vs audio classification by mime type

#### UC-WI11: An invitation token binds the number and opens the member's assistant

#### UC-WI12: A verified message reaches every computer once, about no home

### Cross-context references

- Inbound side of `outbound-messaging-providers`: the same provider
  (WhatsApp) is supported in both directions, but the inbound handler
  belongs to `integration` and the outbound send capability also
  belongs to `integration`. The session-creation step calls into
  `agent_runtime` via the platform's session-create API.
- Uses the hook dispatcher and its contract matcher
  (`local/projects/teleclaude/design/architecture/hook-service`).
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

- The WhatsApp-command router dispatches inbound commands through the
  WhatsApp UI adapter's public dispatch path, injecting WhatsApp-specific
  metadata (platform message id, actor avatar URL) without changing the
  command type surface. When no WhatsApp UI adapter is present it falls
  back to calling the command handler directly (UC-WI6).

- Image type detection prefers the explicit message.image
  classification but falls back to checking mime type starts-with
  "image/"; documents and unknown media types land in `files/`.
- The handler does not verify signatures. The ingress refuses every
  WhatsApp webhook that is not signed with the global WhatsApp secret
  before anything is relayed (see `inbound-webhook-endpoint-framework`).
