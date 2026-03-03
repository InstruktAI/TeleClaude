# DOR Report: missing-client-services

## Draft Assessment

**Phase:** Draft (pre-gate)
**Assessed by:** Claude (prepare router)
**Date:** 2026-03-03

## Gate Assessment

### 1. Intent & Success

**Status:** Satisfied

The problem is clear: `telegram.py` and `email.py` exist as service-layer delivery
helpers, but the equivalent for Discord and WhatsApp was never created. The event
delivery adapter layer (`teleclaude_events/delivery/`) only has Telegram. Both gaps
need filling to achieve platform parity for admin push notifications.

Success criteria are concrete and testable: importable functions with correct signatures,
delivery adapters following the established callback interface, daemon wiring for all
three platforms, and passing unit tests.

### 2. Scope & Size

**Status:** Satisfied

The work is atomic and pattern-following:
- 4 new modules (2 services, 2 delivery adapters)
- 1 export update (`__init__.py`)
- 1 wiring change (daemon.py)
- 4 new test files

Each new module is ~40-60 lines following an established template. Total new code is
estimated at ~400 lines including tests. Well within a single session.

### 3. Verification

**Status:** Satisfied

- Unit tests for service functions (success, error, edge cases)
- Unit tests for delivery adapters (threshold filtering, exception handling)
- `make test` and `make lint` as final gates
- Demo validation scripts verify imports and signatures

### 4. Approach Known

**Status:** Satisfied

The approach is proven — it's the exact same pattern as the existing Telegram
implementation:
- Service: `telegram.py` pattern (httpx, env token, return message ID)
- Delivery adapter: `TelegramDeliveryAdapter` pattern (send_fn callable, level filtering)
- Daemon wiring: same person-config iteration with credential check

Discord REST API for DMs: `POST /users/@me/channels` + `POST /channels/{id}/messages`
(well-documented, used in `invite.py` already for bot resolution).

WhatsApp Cloud API: `POST graph.facebook.com/{version}/{phone_number_id}/messages`
(already used by `WhatsAppAdapter` in the UI adapter layer).

### 5. Research Complete

**Status:** Satisfied

No new third-party dependencies. Both APIs are already used elsewhere in the codebase:
- Discord REST API patterns exist in `invite.py` (resolve_discord_bot_user_id)
- WhatsApp Cloud API patterns exist in `whatsapp_adapter.py` (_send_text_message)
- httpx is already a dependency

### 6. Dependencies & Preconditions

**Status:** Satisfied

- No prerequisite tasks
- Config schemas already exist: `DiscordCreds.user_id`, `WhatsAppCreds.phone_number`
- Person config already supports all needed credential fields
- `DISCORD_BOT_TOKEN` env var already used by Discord adapter
- WhatsApp config (phone_number_id, access_token, api_version) already parsed in config

### 7. Integration Safety

**Status:** Satisfied

- All new modules are additive — no existing code is modified except:
  - `teleclaude_events/delivery/__init__.py` (add exports)
  - `teleclaude/daemon.py` (add registration blocks after existing Telegram block)
- Both changes are incremental and the existing Telegram path is untouched
- If Discord or WhatsApp credentials are not configured for any admin, the adapters
  simply don't register — no impact on existing behavior

### 8. Tooling Impact

**Status:** Automatically satisfied (no tooling changes)

## Blockers

None.

## Assumptions

- The daemon's people-iteration loop (lines ~1693-1718 in daemon.py) can be extended
  in-place with additional platform blocks. This is a straightforward copy-adapt of the
  existing Telegram block.
- Discord DMs require the bot and user to share a guild. This is documented as a known
  limitation, not a blocker — admin users are expected to be in the Discord guild.
- WhatsApp 24-hour messaging window applies. The delivery adapter handles API errors
  gracefully (log and continue), so expired windows don't crash the pipeline.

## Open Questions

None.
