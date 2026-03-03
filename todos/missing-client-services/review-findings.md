# Review Findings: missing-client-services

## Review Scope

Files changed (merge-base to HEAD):

- `teleclaude/services/discord.py` (new)
- `teleclaude/services/whatsapp.py` (new)
- `teleclaude_events/delivery/discord.py` (new)
- `teleclaude_events/delivery/whatsapp.py` (new)
- `teleclaude_events/delivery/__init__.py` (modified)
- `teleclaude/daemon.py` (modified, lines 1720-1784)
- `tests/unit/test_discord_service.py` (new)
- `tests/unit/test_whatsapp_service.py` (new)
- `tests/unit/test_teleclaude_events/test_discord_adapter.py` (new)
- `tests/unit/test_teleclaude_events/test_whatsapp_adapter.py` (new)
- `demos/missing-client-services/demo.md` (new)

## Paradigm-Fit Assessment

1. **Data flow**: Both service modules are standalone httpx-based helpers with no imports from core or adapters. Delivery adapters follow the exact `TelegramDeliveryAdapter` callback pattern. Daemon wiring follows the existing platform registration block pattern. **Pass.**
2. **Component reuse**: Delivery adapters are independent classes with the same interface shape — this is the established pattern (one class per platform, not a parameterized base). **Pass.**
3. **Pattern consistency**: Service functions match the Telegram service signature pattern (async, httpx, token from env/params, truncation warning, error handling). Delivery adapters match the Telegram adapter exactly. **Pass.**

## Critical

None.

## Important

1. **WhatsApp service tests miss 2 of 4 validation guards** — `tests/unit/test_whatsapp_service.py`
   - `send_whatsapp_message` validates `phone_number`, `content`, `phone_number_id`, and `access_token`. Tests only cover `access_token` (`test_missing_access_token_raises`) and `content` (`test_empty_content_raises`). Missing: `phone_number=""` and `phone_number_id=""` test cases.
   - Requirements state: "unit tests covering success, error, and threshold/filtering paths."
   - Severity: Important — the validation logic is trivial and correct, but the test gap is a coverage contract violation.

2. **Bare `KeyError` on malformed 200 responses** — `teleclaude/services/discord.py:72,83` and `teleclaude/services/whatsapp.py:66`
   - Discord: `dm_response.json()["id"]` (line 72) and `msg_response.json()["id"]` (line 83).
   - WhatsApp: `response.json()["messages"][0]["id"]` (line 66).
   - Telegram uses `.get()` throughout (`payload.get("result") or {}`), producing `None` on unexpected shapes rather than crashing.
   - If the API returns a 200 with unexpected JSON (rare but possible), a bare `KeyError`/`IndexError` propagates with no contextual message, versus a descriptive `RuntimeError`.
   - Severity: Important — pattern deviation from Telegram; low probability but poor diagnostic ergonomics.

## Suggestions

1. **`msg_response` error check outside `async with`** — `teleclaude/services/discord.py:76-81`
   - The `dm_response` error check is inside the `async with` block (line 60); the `msg_response` check is outside (line 76). Functionally correct (httpx buffers bodies), but inconsistent placement within the same function.

2. **Import aliasing in daemon.py** — lines 1723-1724, 1754-1755
   - `load_global_config` and `load_person_config` are re-imported under aliases (`_load_global_config_discord`, `_load_person_config_whatsapp`) in each platform block. This is because each block is self-contained (Telegram may be disabled). Consider hoisting the loader imports above the platform blocks to eliminate the aliases.

3. **`people_dir` computed three times** — `daemon.py:1695,1722,1751`
   - `Path("~/.teleclaude/people").expanduser()` is evaluated in each platform block. Could be computed once before the blocks.

4. **Non-JSON error body paths untested** — both `test_discord_service.py` and `test_whatsapp_service.py`
   - Both services have `except Exception: detail = response.text[:200]` fallback for malformed JSON error bodies. `test_telegram.py` covers this path; the new tests do not.

5. **Whitespace-only content** — `test_discord_service.py`, `test_whatsapp_service.py`
   - Both services check `not content.strip()`. Tests only pass `content=""` (falsy), not `content="   "` (truthy but whitespace-only). Adding a whitespace test would exercise the `.strip()` branch.

## Demo Artifact Review

- `demos/missing-client-services/demo.md` contains five executable blocks: file existence checks, import verification, signature inspection, and test execution.
- Cross-checked against implementation: all import paths, class names, and function signatures match the actual code.
- The demo is structural (validates existence and importability) rather than behavioral (no mock API calls), which is appropriate for API-dependent services.
- No fabricated output. No stale commands or flags.
- **Pass.**

## Why No Critical Issues

1. **Paradigm-fit verified**: All new code follows the two-layer service+adapter pattern. No inline hacks, no core imports from services, no adapter bypass.
2. **Requirements traced**: Each success criterion maps to implemented code and tests. Discord DM flow (2-step: create channel, send message), WhatsApp Cloud API flow, delivery adapters with level filtering, daemon wiring with credential binding — all present.
3. **Copy-paste duplication checked**: Delivery adapters are structurally identical by design (one per platform). The daemon wiring blocks repeat the admin-iteration pattern — this follows the existing Telegram block and is not new duplication introduced by this change.
4. **Token sourcing**: Requirements explicitly specify `DISCORD_BOT_TOKEN` env var for the Discord service, consistent with `send_telegram_dm`'s `TELEGRAM_BOT_TOKEN` env var pattern. The config-first pattern in `discord_adapter.py` (interactive sessions) is a different concern.

## Verdict

**APPROVE**

The implementation is correct, follows established patterns closely, and has comprehensive test coverage for the main paths. The Important findings are a test coverage gap (2 missing WhatsApp validation tests) and a robustness concern (bare key access vs `.get()`). Both are real but not blocking — the validation logic is trivially correct, and the key-access paths are reached only after HTTP status checks confirm a successful response.
