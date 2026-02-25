# DOR Report: help-desk-whatsapp

## Gate Verdict

**Date:** 2026-02-23T19:15:00Z
**Phase:** Gate (formal validation)
**Assessor:** Architect (gate mode)
**Status:** `pass`
**Score:** 9/10

---

## Gate Assessment

### Gate 1: Intent & Success -- PASS

Requirements clearly state the problem (add WhatsApp as a customer-facing messaging channel for the help desk platform) and the intended outcome (bidirectional messaging with AI agent responses, escalation relay, identity resolution). 13 success criteria are concrete and testable with observable behaviors and measurable thresholds (e.g., "typing indicator fires within ~200ms", "messages outside 24h window use template messages").

### Gate 2: Scope & Size -- PASS

5 implementation phases, ~20 tasks. The work is a single cohesive adapter following an established pattern. In-scope/out-of-scope boundaries are explicit. Cross-cutting changes are limited to established extension points (`models.py`, `adapter_client.py`, `config/schema.py`). The dependency on `inbound-hook-service` is correctly declared as a prerequisite, not bundled into this work.

### Gate 3: Verification -- PASS

Clear test plan covering unit tests (9 test categories in Task 4.1) and integration tests (4 flow tests in Task 4.2). Edge cases identified: 24h window boundary, E.164 phone number normalization, rate limit handling with backoff, message splitting for >4096 chars. Quality gates explicit (`make test`, `make lint`).

### Gate 4: Approach Known -- PASS

Two existing adapters (`TelegramAdapter`, `DiscordAdapter`) follow the exact same pattern: `UiAdapter` subclass with `ADAPTER_KEY`, `*AdapterMetadata` dataclass in `models.py`, lazy `get_*()` method in `UiAdapterMetadata`, config-guarded registration in `AdapterClient.start()`. The plan replicates this proven pattern precisely. `httpx` async client is already the standard HTTP client in the codebase.

### Gate 5: Research Complete -- PASS (remediated)

All 5 WhatsApp Business Cloud API docs exist under `docs/third-party/whatsapp/` and are indexed in `docs/third-party/index.yaml`:

| Doc                     | Coverage                                                      | Key details verified                                                                                                                   |
| ----------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `cloud-api.md`          | Core concepts, auth, constraints, API versioning              | E.164 format, 4096/1024 char limits, `messaging_product` requirement, v20.0 validity                                                   |
| `messages-api.md`       | Send text/media/template, mark as read, reply context         | Exact POST payloads, `wamid` response format, template component structure                                                             |
| `media-api.md`          | Upload, retrieve URL, download                                | Multipart upload, 2-step download flow, MIME types, size limits, 30-day media ID lifecycle                                             |
| `webhooks.md`           | Verification challenge, HMAC-SHA256, payload structure        | `hub.mode/verify_token/challenge`, `X-Hub-Signature-256`, all message types including voice (`audio/ogg; codecs=opus`), status updates |
| `rate-limits-errors.md` | Messaging tiers, API rate limits, error codes, retry strategy | 80 msg/s, 131xxx error codes, 429 backoff, permanent vs. transient failures                                                            |

Sources are authoritative (Meta developer documentation). Every API surface referenced in the requirements is covered.

### Gate 6: Dependencies & Preconditions -- PASS (remediated)

- `inbound-hook-service` in `roadmap.yaml`: DOR score 9, status `pass`, ready for build.
- `help-desk-whatsapp` in `roadmap.yaml`: sequenced with `after: [inbound-hook-service]`.
- Required credentials documented in config schema (env vars: `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_WEBHOOK_SECRET`, `WHATSAPP_VERIFY_TOKEN`).
- Existing codebase infrastructure confirmed: `NormalizerRegistry` in `hooks/inbound.py`, `InboundEndpointRegistry` in `hooks/inbound.py` and `hooks/config.py`, `HookEvent` in `hooks/webhook_models.py`, voice message handler in `core/voice_message_handler.py`.

### Gate 7: Integration Safety -- PASS

The adapter activates only when WhatsApp credentials are configured (same config-guard pattern as Telegram/Discord in `AdapterClient.start()`). No modifications to existing adapter behavior. New files (`whatsapp_adapter.py`, normalizer, handler) are additive. Extension points (`models.py`, `adapter_client.py`, `config/schema.py`) are established patterns with no risk to existing functionality.

### Gate 8: Tooling Impact -- N/A (automatically satisfied)

No tooling or scaffolding changes. This is a new adapter following existing patterns.

### Plan-to-Requirement Fidelity -- PASS

All 13 in-scope requirements trace to implementation tasks:

| #   | Requirement                 | Implementation Task                                |
| --- | --------------------------- | -------------------------------------------------- |
| 1   | WhatsApp UI adapter         | Task 2.1: Adapter class scaffold                   |
| 2   | Adapter metadata model      | Task 1.1: WhatsApp adapter metadata                |
| 3   | Configuration schema        | Task 1.2: WhatsApp config schema                   |
| 4   | Identity resolution         | Task 1.3: Identity resolution for WhatsApp         |
| 5   | WhatsApp normalizer         | Task 3.1: WhatsApp normalizer                      |
| 6   | Inbound message handler     | Task 3.2: Inbound message handler                  |
| 7   | Typing indicator            | Task 2.4: Typing indicator and read receipts       |
| 8   | Media handling (inbound)    | Task 3.2: Media download helper                    |
| 9   | Voice message transcription | Task 3.2: Voice/audio dispatch to Whisper pipeline |
| 10  | Media handling (outbound)   | Task 2.3: `send_file()` with media upload          |
| 11  | 24-hour messaging window    | Task 2.3: Window tracking + template fallback      |
| 12  | Adapter registration        | Task 2.6: Registration in `AdapterClient.start()`  |
| 13  | Markdown conversion         | Task 2.5: Platform-specific overrides              |

No contradictions found between plan and requirements. The plan prescribes `UiAdapter` subclass (matching requirement "UiAdapter subclass"), `httpx` for HTTP calls (matching constraint), and established patterns confirmed by codebase inspection.

---

## Assumptions

- The existing `UiAdapter` base class and `AdapterClient` broadcast pattern are stable.
- WhatsApp Business Cloud API v20.0 is a valid pinning target (confirmed via research docs).
- The help desk platform patterns (customer sessions, identity resolution, escalation relay) are stable.
- Meta's webhook payload structure follows the documented format (confirmed via official docs).
- The `InboundEndpointRegistry` GET handler supports WhatsApp's `hub.verify_token` challenge format (to be verified during `inbound-hook-service` implementation).

## Open Questions

1. **Template message setup** -- Operational concern. The adapter logs a warning when attempting out-of-window messaging without a configured template. Template provisioning is a deployment task, not a code task. Non-blocking.

2. **WhatsApp API version** -- Confirmed: `v20.0` is valid. Pinning strategy is sound. Resolved.
