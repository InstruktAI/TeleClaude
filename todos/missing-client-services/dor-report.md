# DOR Report: missing-client-services

## Gate Verdict

**Phase:** Gate (formal DOR validation)
**Assessed by:** Claude (gate worker)
**Date:** 2026-03-03
**Score:** 9/10
**Status:** pass

## Gate Assessment

### 1. Intent & Success

**Status:** Satisfied

The problem is clear: `telegram.py` and `email.py` exist as service-layer delivery
helpers, but the equivalent for Discord and WhatsApp was never created. The event
delivery adapter layer (`teleclaude_events/delivery/`) only has Telegram. Both gaps
need filling to achieve platform parity for admin push notifications.

Success criteria are concrete and testable: 9 specific checkboxes covering importable
functions with correct signatures, delivery adapters following the established callback
interface, daemon wiring for all platforms, and passing unit tests.

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

- Unit tests for service functions (success, error, edge cases) — 5 test cases each
  following `test_telegram.py` pattern
- Unit tests for delivery adapters (threshold filtering, exception handling) — 5 test
  cases each following the existing delivery adapter test pattern
- `make test` and `make lint` as final gates
- Demo validation scripts verify imports and signatures

### 4. Approach Known

**Status:** Satisfied

The approach is proven — direct replication of the existing Telegram implementation:
- Service: `telegram.py` pattern (httpx, env token, return message ID)
- Delivery adapter: `TelegramDeliveryAdapter` pattern (send_fn callable, level filtering,
  identical `on_notification` signature)
- Daemon wiring: same person-config iteration with credential check (lines 1693-1718)

Discord REST API for DMs: `POST /users/@me/channels` + `POST /channels/{id}/messages`
(already used in `invite.py` for bot resolution).

WhatsApp Cloud API: `POST graph.facebook.com/{version}/{phone_number_id}/messages`
(already used by `WhatsAppAdapter` in the UI adapter layer).

### 5. Research Complete

**Status:** Satisfied (automatically — no new dependencies)

No new third-party dependencies. Both APIs are already used elsewhere in the codebase:
- Discord REST API patterns exist in `invite.py` (resolve_discord_bot_user_id)
- WhatsApp Cloud API patterns exist in `whatsapp_adapter.py` (_send_text_message)
- httpx is already a dependency

### 6. Dependencies & Preconditions

**Status:** Satisfied

- No prerequisite tasks
- Config schemas exist: `DiscordCreds.user_id`, `WhatsAppCreds.phone_number`
  (`teleclaude/config/schema.py:138-145`)
- Person config already supports all needed credential fields
  (`CredsConfig` at schema.py:148)
- `DISCORD_BOT_TOKEN` env var already used by Discord adapter
- WhatsApp config (`phone_number_id`, `access_token`, `api_version`) already parsed
  in global config (`WhatsAppConfig` in `teleclaude/config/__init__.py:201`)
- No new configuration keys or wizard exposure needed

### 7. Integration Safety

**Status:** Satisfied

- All new modules are additive — no existing code is modified except:
  - `teleclaude_events/delivery/__init__.py` (add exports)
  - `teleclaude/daemon.py` (add registration blocks after existing Telegram block)
- Both changes are incremental and the existing Telegram path is untouched
- Discord block gates on `config.discord.enabled`, WhatsApp on `config.whatsapp.enabled`
- If credentials are not configured for any admin, adapters don't register — no impact

### 8. Tooling Impact

**Status:** Automatically satisfied (no tooling changes)

## Plan-to-Requirement Fidelity

All implementation plan tasks trace directly to requirements:
- Task 1.1 → Requirement: `teleclaude/services/discord.py`
- Task 1.2 → Requirement: `teleclaude/services/whatsapp.py`
- Task 2.1 → Requirement: `teleclaude_events/delivery/discord.py`
- Task 2.2 → Requirement: `teleclaude_events/delivery/whatsapp.py`
- Task 2.3 → Requirement: Update `__init__.py` exports
- Task 3.1 → Requirement: Wire into daemon.py
- Tasks 4.1-4.3 → Requirement: Unit tests and quality checks

No task contradicts a requirement. The plan prescribes the exact same pattern
(httpx, standalone helpers, `on_notification` callback) that requirements specify.

## Actions Taken

- Tightened daemon wiring section (Task 3.1) with verified config structure:
  `config.discord` and `config.whatsapp` are always-present dataclass instances
  (DiscordConfig and WhatsAppConfig), gated by `.enabled` flags. Resolved the
  draft's uncertainty about Discord config gating.
- Specified WhatsApp API param binding source: `config.whatsapp.phone_number_id`,
  `config.whatsapp.access_token`, `config.whatsapp.api_version`.

## Blockers

None.

## Assumptions

- Discord DMs require the bot and user to share a guild. This is an inherent Discord
  limitation, documented as a known constraint in requirements — not a blocker.
- WhatsApp 24-hour messaging window applies. The delivery adapter handles API errors
  gracefully (log and continue), so expired windows don't crash the pipeline.
