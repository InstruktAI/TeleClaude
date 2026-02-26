# Requirements: help-desk-whatsapp

## Goal

Add WhatsApp Business Cloud API as a customer-facing messaging channel for TeleClaude's help desk platform. Customers contact support via WhatsApp; AI agents respond; human operators can take over via the existing escalation relay mechanism.

## Scope

### In scope

1. **WhatsApp UI adapter** (`teleclaude/adapters/whatsapp_adapter.py`) — `UiAdapter` subclass handling outbound messaging (text, media, read receipts).
2. **Adapter metadata model** — `WhatsAppAdapterMetadata` dataclass in `models.py`, integrated into `UiAdapterMetadata` and `SessionAdapterMetadata` (same pattern as Telegram/Discord).
3. **Configuration schema** — `WhatsAppConfig` section in config schema, activated by credentials in env/config.
4. **Identity resolution** — Map WhatsApp phone numbers to person records via `creds.whatsapp.phone_number` in people config. Unknown numbers default to `customer` role.
5. **WhatsApp normalizer** — Transform Meta's webhook payload structure (`entry[].changes[].value.messages[]`) into canonical `HookEvent`. Registered via `NormalizerRegistry` as a built-in global normalizer.
6. **Inbound message handler** — Bridge `HookEvent` to adapter pipeline: resolve/create customer session, inject message into session, trigger AI response. Ships as a built-in global subscription handler.
7. **Typing indicator** — Override `send_typing_indicator()` using WhatsApp's "mark as read" API (`status: "read"`) as the typing equivalent. Fire-and-forget pattern matching Telegram/Discord.
8. **Media handling (inbound)** — Download images, documents, and audio via WhatsApp Media API (`GET /{media_id}` for URL, then download). Save to session workspace using established file handling patterns.
9. **Voice message transcription** — Download voice notes (audio/ogg), pass to shared Whisper pipeline via `_process_voice_input()`.
10. **Media handling (outbound)** — Upload media via WhatsApp Media API, send as media messages.
11. **24-hour messaging window** — Track last customer message timestamp. Use pre-approved template messages when sending outside the 24h window. Within the window, send free-form messages.
12. **Adapter registration** — Register in `AdapterClient.start()` when WhatsApp config is present and enabled. Same pattern as Telegram/Discord.
13. **Markdown conversion** — Override `_convert_markdown_for_platform()` to strip/convert unsupported markdown (WhatsApp supports bold, italic, strikethrough, monospace only).

### Out of scope

- Wiring `InboundEndpointRegistry` into the daemon (prerequisite: `inbound-hook-service`).
- Starting the subscription worker (prerequisite: `inbound-hook-service`).
- WhatsApp Business API account provisioning and Meta app setup.
- Interactive message types (buttons, lists, location sharing) — future enhancement.
- WhatsApp Business catalog/product features.
- Group chat support.
- Outbound proactive messaging (business-initiated conversations beyond session replies).
- Payment/billing API integration.

## Success Criteria

- [ ] A WhatsApp message from a new phone number creates a customer session in the configured help desk workspace.
- [ ] AI agent responses are delivered back to the customer's WhatsApp within the platform's delivery latency.
- [ ] Typing indicator (read receipt) fires within ~200ms of receiving a customer message, using the same fire-and-forget error suppression pattern as other adapters.
- [ ] Voice messages are transcribed via Whisper and injected as text into the AI session.
- [ ] Image/document attachments are downloaded to the session workspace and available to the AI agent.
- [ ] Outbound file/image sending works via `send_file()`.
- [ ] Customer identity is resolved: known phone numbers map to person records with appropriate roles; unknown numbers get `customer` role.
- [ ] Escalation via `telec sessions escalate()` creates a Discord relay thread; admin messages in the relay thread are forwarded to the customer's WhatsApp.
- [ ] Messages outside the 24-hour window use template messages instead of free-form text.
- [ ] WhatsApp adapter metadata persists across daemon restarts (stored in DB via session adapter_metadata).
- [ ] Adapter starts only when WhatsApp credentials are configured; missing credentials skip startup gracefully.
- [ ] `make test` passes with new WhatsApp adapter tests (unit tests with mocked API calls).
- [ ] `make lint` passes.

## Constraints

- **Dependency:** Requires `inbound-hook-service` to be delivered first for webhook reception. The adapter can be developed and tested with mocked inbound events, but end-to-end flow requires the hook service.
- **API version:** Pin to WhatsApp Cloud API `v21.0` (v20.0 expired May 2025; v21.0+ required as of Sep 2025).
- **HTTP client:** Use `httpx` (async) for all WhatsApp API calls — consistent with existing codebase patterns. No third-party WhatsApp SDK.
- **Message size:** WhatsApp text messages are limited to 4096 characters; captions to 1024 characters. Long outputs must be split or truncated.
- **Rate limits:** WhatsApp Business API has throughput limits (varies by tier). Implement basic retry with backoff for 429 responses.
- **Template messages:** At least one pre-approved message template must exist in the WhatsApp Business account for out-of-window messaging. Template name/ID is configurable.

## Risks

- **Meta API changes:** WhatsApp Cloud API is versioned but Meta occasionally deprecates features. Mitigation: pin API version, monitor deprecation notices.
- **Webhook reliability:** Meta retries failed webhook deliveries but gaps are possible. Mitigation: idempotent message processing keyed on WhatsApp message ID.
- **24-hour window edge cases:** Business-initiated messages outside the window require pre-approved templates. If no template is configured, messages are silently dropped by Meta. Mitigation: log a warning when attempting out-of-window messaging without a template.
- **Phone number format normalization:** WhatsApp uses E.164 format. Identity resolution must normalize input numbers. Mitigation: strip non-numeric chars, ensure leading `+` or country code.
